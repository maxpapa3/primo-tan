#!/usr/bin/env python3
"""Push-to-talk voice client for Radxa Zero 3W + Whisplay HAT."""

from __future__ import annotations

import argparse
import base64
import json
import os
import select
import struct
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen

EV_KEY = 0x01
KEY_PRESS = 1
KEY_RELEASE = 0
EVENT_STRUCT = struct.Struct("llHHI")
DISPLAY_PROCESS: subprocess.Popen | None = None
CAMERA_PROCESS: subprocess.Popen | None = None
CAMERA_IMAGE = Path("/tmp/primo-camera/latest.jpg")


def start_face(state: str, enabled: bool, question: str | None = None, answer: str | None = None) -> None:
    global DISPLAY_PROCESS
    if not enabled:
        return
    stop_face()
    start_camera(enabled)
    command = [sys.executable, "-u", "face_display.py", "--state", state]
    command.extend(["--camera-image", str(CAMERA_IMAGE)])
    if question:
        command.extend(["--question", question])
    if answer:
        command.extend(["--answer", answer])
    DISPLAY_PROCESS = subprocess.Popen(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def stop_face() -> None:
    global DISPLAY_PROCESS
    if DISPLAY_PROCESS is None:
        return
    if DISPLAY_PROCESS.poll() is None:
        DISPLAY_PROCESS.terminate()
        try:
            DISPLAY_PROCESS.wait(timeout=1)
        except subprocess.TimeoutExpired:
            DISPLAY_PROCESS.kill()
            DISPLAY_PROCESS.wait(timeout=1)
    DISPLAY_PROCESS = None


def start_camera(enabled: bool) -> None:
    global CAMERA_PROCESS
    if not enabled:
        return
    if CAMERA_PROCESS is not None and CAMERA_PROCESS.poll() is None:
        return

    CAMERA_IMAGE.parent.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        "-u",
        "camera_capture.py",
        "--device",
        os.environ.get("PRIMO_CAMERA_DEVICE", "/dev/video0"),
        "--output",
        str(CAMERA_IMAGE),
        "--rotate",
        os.environ.get("PRIMO_CAMERA_ROTATE", "0"),
    ]
    CAMERA_PROCESS = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def stop_camera() -> None:
    global CAMERA_PROCESS
    if CAMERA_PROCESS is None:
        return
    if CAMERA_PROCESS.poll() is None:
        CAMERA_PROCESS.terminate()
        try:
            CAMERA_PROCESS.wait(timeout=2)
        except subprocess.TimeoutExpired:
            CAMERA_PROCESS.kill()
            CAMERA_PROCESS.wait(timeout=2)
    CAMERA_PROCESS = None


def flash_face(state: str, enabled: bool, duration: float = 1.5) -> None:
    if not enabled:
        return
    subprocess.Popen(
        [sys.executable, "-u", "face_display.py", "--state", state, "--duration", str(duration)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def post_audio(url: str, wav_path: Path) -> dict:
    data = wav_path.read_bytes()
    request = Request(url, data=data, headers={"Content-Type": "audio/wav"}, method="POST")
    with urlopen(request, timeout=240) as response:
        return json.loads(response.read().decode("utf-8"))


def post_json(url: str, payload: dict) -> dict:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = Request(url, data=data, headers={"Content-Type": "application/json; charset=utf-8"}, method="POST")
    with urlopen(request, timeout=240) as response:
        return json.loads(response.read().decode("utf-8"))


def latest_camera_b64() -> str | None:
    if not CAMERA_IMAGE.exists():
        return None
    try:
        return base64.b64encode(CAMERA_IMAGE.read_bytes()).decode("ascii")
    except OSError:
        return None


def download(url: str, destination: Path) -> None:
    with urlopen(url, timeout=60) as response:
        destination.write_bytes(response.read())


def play_audio(path: Path, device: str | None = None) -> None:
    command = ["aplay"]
    if device:
        command.extend(["-D", device])
    command.append(str(path))
    subprocess.run(command, check=False)


def talk_payload(text: str, meta: dict | None = None) -> dict:
    payload = {"text": text, "meta": meta or {}}
    image_b64 = latest_camera_b64()
    if image_b64:
        payload["image_b64"] = image_b64
    return payload


def transcribe_audio(server: str, wav_path: Path) -> str:
    base_url = server.rstrip("/") + "/"
    transcribe_url = urljoin(base_url, "transcribe-audio")
    transcribed = post_audio(transcribe_url, wav_path)
    if not transcribed.get("ok", False):
        print(json.dumps(transcribed, ensure_ascii=False), file=sys.stderr)
        return ""
    return str(transcribed.get("transcript", "")).strip()


def clear_text_after_delay(face: bool, delay: float = 3.0) -> None:
    if not face:
        return
    time.sleep(delay)
    start_face("idle", face)


def start_recording(path: Path, device: str, rate: int) -> subprocess.Popen:
    return subprocess.Popen(
        [
            "arecord",
            "-q",
            "-D",
            device,
            "-f",
            "S16_LE",
            "-c",
            "1",
            "-r",
            str(rate),
            "-t",
            "wav",
            str(path),
        ]
    )


def stop_recording(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=3)


def wait_for_button_recording(event_path: str, code: int | None, output_path: Path, device: str, rate: int) -> bool:
    print(f"Waiting for button on {event_path}. Hold to speak, release to send.")
    active_code: int | None = None
    recorder: subprocess.Popen | None = None
    started_at = 0.0

    with open(event_path, "rb", buffering=0) as event_file:
        while True:
            readable, _, _ = select.select([event_file], [], [], 0.5)
            if not readable:
                continue

            data = event_file.read(EVENT_STRUCT.size)
            if len(data) != EVENT_STRUCT.size:
                continue
            _, _, event_type, event_code, value = EVENT_STRUCT.unpack(data)
            if event_type != EV_KEY:
                continue
            if code is not None and event_code != code:
                continue

            if value == KEY_PRESS and recorder is None:
                active_code = event_code
                started_at = time.monotonic()
                print(f"Recording... key={event_code}")
                recorder = start_recording(output_path, device, rate)
            elif value == KEY_RELEASE and recorder is not None and event_code == active_code:
                stop_recording(recorder)
                elapsed = time.monotonic() - started_at
                print(f"Recorded {elapsed:.1f}s")
                return elapsed >= 0.3


def gpio_value_reader(chip: int, line: int):
    import gpiod

    if hasattr(gpiod, "LineSettings"):
        from gpiod.line import Bias, Direction, Value

        gpio_chip = gpiod.Chip(f"/dev/gpiochip{chip}")
        try:
            try:
                settings = gpiod.LineSettings(direction=Direction.INPUT, bias=Bias.DISABLED)
            except Exception:
                settings = gpiod.LineSettings(direction=Direction.INPUT)
            request = gpio_chip.request_lines(consumer="radxa-mascot-button", config={line: settings})

            def read() -> int:
                return 1 if request.get_value(line) == Value.ACTIVE else 0

            try:
                yield read
            finally:
                request.release()
        finally:
            gpio_chip.close()
    else:
        gpio_chip = gpiod.Chip(f"gpiochip{chip}")
        gpio_line = gpio_chip.get_line(line)
        try:
            try:
                gpio_line.request(
                    consumer="radxa-mascot-button",
                    type=gpiod.LINE_REQ_DIR_IN,
                    flags=gpiod.LINE_REQ_FLAG_BIAS_DISABLE,
                )
            except Exception:
                gpio_line.request(consumer="radxa-mascot-button", type=gpiod.LINE_REQ_DIR_IN)

            def read() -> int:
                return int(gpio_line.get_value())

            try:
                yield read
            finally:
                gpio_line.release()
        finally:
            gpio_chip.close()


def wait_for_gpio_recording(chip: int, line: int, output_path: Path, device: str, rate: int, face: bool) -> bool:
    print(f"Waiting for GPIO button gpiochip{chip} line {line}. Hold to speak, release to send.")
    recorder: subprocess.Popen | None = None
    started_at = 0.0
    previous = 0

    reader_context = gpio_value_reader(chip, line)
    read_value = next(reader_context)
    try:
        while True:
            value = read_value()
            if value != previous:
                previous = value
                if value == 1 and recorder is None:
                    started_at = time.monotonic()
                    print("Recording...")
                    start_face("listening", face)
                    recorder = start_recording(output_path, device, rate)
                elif value == 0 and recorder is not None:
                    stop_recording(recorder)
                    start_face("thinking", face)
                    elapsed = time.monotonic() - started_at
                    print(f"Recorded {elapsed:.1f}s")
                    return elapsed >= 0.3
            time.sleep(0.01)
    finally:
        try:
            next(reader_context)
        except StopIteration:
            pass


def fixed_recording(seconds: float, output_path: Path, device: str, rate: int, face: bool) -> bool:
    print(f"Recording for {seconds:.1f}s...")
    start_face("listening", face)
    process = start_recording(output_path, device, rate)
    time.sleep(seconds)
    stop_recording(process)
    start_face("thinking", face)
    return True


def display_and_play_reply(
    reply: dict,
    question: str,
    playback_device: str | None,
    no_play: bool,
    face: bool,
    clear_after: bool = True,
) -> int:
    if not reply.get("ok", False):
        print(json.dumps(reply, ensure_ascii=False), file=sys.stderr)
        start_face("sad", face)
        return 1

    emotion = reply.get("emotion", "neutral")
    text = reply.get("text", "")
    print(f"[{emotion}] {text}")

    audio_url = reply.get("audio_url")
    if audio_url:
        print(f"audio: {audio_url}")
    if audio_url and not no_play:
        with tempfile.TemporaryDirectory() as tmp:
            audio_path = Path(tmp) / "reply.wav"
            download(str(audio_url), audio_path)
            start_face("speaking", face, question, str(text))
            play_audio(audio_path, playback_device)
            start_face("idle", face, question, str(text))
            if clear_after:
                clear_text_after_delay(face)
    else:
        start_face("idle", face, question, str(text))
        if clear_after:
            clear_text_after_delay(face)
    return 0


def send_spontaneous(server: str, playback_device: str | None, no_play: bool, face: bool) -> int:
    base_url = server.rstrip("/") + "/"
    talk_url = urljoin(base_url, "talk")
    prompt = "いま見えているものや今の気分について、短い独り言をひとつ言ってください。"
    meta = {"source": "spontaneous", "client": "radxa", "camera": "raspi"}
    try:
        reply = post_json(talk_url, talk_payload(prompt, meta))
    except HTTPError as exc:
        print(f"server returned HTTP {exc.code}", file=sys.stderr)
        return 1
    except URLError as exc:
        print(f"cannot reach server: {exc.reason}", file=sys.stderr)
        return 1
    return display_and_play_reply(reply, "ひとりごと", playback_device, no_play, face)


def send_and_play(server: str, wav_path: Path, playback_device: str | None, no_play: bool, face: bool) -> int:
    base_url = server.rstrip("/") + "/"
    talk_url = urljoin(base_url, "talk")
    talk_audio_url = urljoin(base_url, "talk-audio")
    try:
        transcript = transcribe_audio(server, wav_path)
        print(f"you: {transcript}")
        if transcript:
            start_face("thinking", face, transcript, "")
        else:
            start_face("idle", face, "", "聞き取れませんでした。もう一度お願いします。")
            print("[confused] 聞き取れませんでした。もう一度お願いします。")
            clear_text_after_delay(face)
            return 0

        payload = talk_payload(transcript, {"source": "audio", "client": "radxa", "camera": "raspi"})
        reply = post_json(talk_url, payload)
        reply["transcript"] = transcript
    except HTTPError as exc:
        if exc.code == 404:
            try:
                reply = post_audio(talk_audio_url, wav_path)
            except HTTPError as fallback_exc:
                print(f"server returned HTTP {fallback_exc.code}", file=sys.stderr)
                return 1
            except URLError as fallback_exc:
                print(f"cannot reach server: {fallback_exc.reason}", file=sys.stderr)
                return 1
        else:
            print(f"server returned HTTP {exc.code}", file=sys.stderr)
            return 1
    except URLError as exc:
        print(f"cannot reach server: {exc.reason}", file=sys.stderr)
        return 1

    transcript = reply.get("transcript", "")
    return display_and_play_reply(reply, str(transcript), playback_device, no_play, face)


def run_interaction(args: argparse.Namespace) -> int:
    with tempfile.TemporaryDirectory() as tmp:
        wav_path = Path(tmp) / "utterance.wav"
        if args.mode == "fixed":
            ok = fixed_recording(args.seconds, wav_path, args.capture_device, args.rate, not args.no_face)
        elif args.mode == "gpio-button":
            ok = wait_for_gpio_recording(args.gpio_chip, args.gpio_line, wav_path, args.capture_device, args.rate, not args.no_face)
        else:
            ok = wait_for_button_recording(args.event, args.code, wav_path, args.capture_device, args.rate)
        if not ok or not wav_path.exists() or wav_path.stat().st_size < 1024:
            print("recording was too short or empty", file=sys.stderr)
            start_face("idle", not args.no_face)
            return 1
        return send_and_play(args.server, wav_path, args.playback_device, args.no_play, not args.no_face)


def main() -> None:
    parser = argparse.ArgumentParser(description="Push-to-talk voice client.")
    parser.add_argument("--server", required=True, help="Example: http://<mac-mini-ip>:8765")
    parser.add_argument("--mode", choices=["gpio-button", "button", "fixed"], default="gpio-button")
    parser.add_argument("--event", default="/dev/input/event0", help="Input event device for button mode.")
    parser.add_argument("--code", type=int, help="EV_KEY code to accept. If omitted, first pressed key is used.")
    parser.add_argument("--gpio-chip", type=int, default=3, help="GPIO chip number for gpio-button mode.")
    parser.add_argument("--gpio-line", type=int, default=1, help="GPIO line offset for gpio-button mode.")
    parser.add_argument("--seconds", type=float, default=4.0, help="Recording length for fixed mode.")
    parser.add_argument("--capture-device", default="plughw:CARD=wm8960soundcard,DEV=0")
    parser.add_argument("--playback-device", default="plughw:CARD=wm8960soundcard,DEV=0")
    parser.add_argument("--rate", type=int, default=16000)
    parser.add_argument("--no-play", action="store_true")
    parser.add_argument("--no-face", action="store_true", help="Disable /dev/fb0 face animation.")
    parser.add_argument("--loop", action="store_true", help="Keep waiting for the next utterance.")
    args = parser.parse_args()

    if not args.no_face:
        start_face("idle", True)

    if not args.loop:
        try:
            raise SystemExit(run_interaction(args))
        finally:
            stop_face()

    try:
        while True:
            code = run_interaction(args)
            if code != 0:
                time.sleep(1)
    finally:
        stop_face()


if __name__ == "__main__":
    main()
