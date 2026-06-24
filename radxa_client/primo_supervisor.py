#!/usr/bin/env python3
"""Always-on button supervisor for Primo-tan.

Double-click toggles mascot mode. While active, holding the button records speech.
When the camera view changes enough, Primo-tan may comment on what she sees.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from PIL import Image

from voice_client import (
    CAMERA_IMAGE,
    display_and_play_reply,
    gpio_value_reader,
    post_json,
    send_and_play,
    send_visual_change,
    start_face,
    start_recording,
    stop_camera,
    stop_face,
    stop_recording,
    talk_payload,
    transcribe_audio,
)


def console_mode(mode: str) -> None:
    subprocess.run(["sudo", "-n", "/usr/local/sbin/primo-console-mode", mode], check=False)


class PrimoSupervisor:
    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.active = bool(args.start_active)
        self.click_count = 0
        self.click_deadline = 0.0
        self.recording_process: subprocess.Popen | None = None
        self.recording_path: Path | None = None
        self.press_started_at = 0.0
        self.hold_recording_started = False
        self.visual_thread: threading.Thread | None = None
        self.next_visual_check_at = 0.0
        self.last_visual_sample: bytes | None = None
        self.last_visual_monologue_at = 0.0
        self.shutdown_confirming = False

    def set_active(self, active: bool) -> None:
        if self.active == active:
            return
        self.active = active
        if active:
            print("Primo-tan ON", flush=True)
            console_mode("mascot")
            start_face("idle", True)
            self.reset_visual_watch()
        else:
            print("Primo-tan OFF", flush=True)
            self.cancel_recording()
            self.reset_visual_watch(clear_sample=True)
            stop_face()
            stop_camera()
            console_mode("console")

    def initialize_state(self) -> None:
        if self.active:
            console_mode("mascot")
            start_face("idle", True)
            self.reset_visual_watch()
            print("Primo-tan ON", flush=True)
        else:
            stop_face()
            console_mode("console")
            print("Primo-tan OFF", flush=True)

    def toggle(self) -> None:
        self.set_active(not self.active)

    def reset_clicks(self) -> None:
        self.click_count = 0
        self.click_deadline = 0.0

    def cancel_recording(self) -> None:
        if self.recording_process is not None:
            stop_recording(self.recording_process)
        self.recording_process = None
        self.recording_path = None
        self.hold_recording_started = False

    def visual_watch_enabled(self) -> bool:
        return not self.args.no_visual_watch and self.args.visual_watch_interval > 0

    def visual_monologue_running(self) -> bool:
        return self.visual_thread is not None and self.visual_thread.is_alive()

    def reset_visual_watch(self, clear_sample: bool = False) -> None:
        if clear_sample:
            self.last_visual_sample = None
            self.last_visual_monologue_at = 0.0
        if not self.active or not self.visual_watch_enabled():
            self.next_visual_check_at = 0.0
            return
        self.next_visual_check_at = time.monotonic() + self.args.visual_watch_interval

    def visual_sample(self) -> bytes | None:
        if not CAMERA_IMAGE.exists():
            return None
        try:
            with Image.open(CAMERA_IMAGE) as image:
                return image.convert("L").resize((32, 24)).tobytes()
        except Exception as exc:
            print(f"camera sample failed: {exc}", flush=True)
            return None

    def visual_change_score(self, sample: bytes) -> float:
        previous = self.last_visual_sample
        if previous is None or len(previous) != len(sample):
            self.last_visual_sample = sample
            return 0.0
        total = sum(abs(a - b) for a, b in zip(previous, sample))
        self.last_visual_sample = sample
        return total / len(sample)

    def start_visual_monologue(self, score: float) -> None:
        if not self.active or self.visual_monologue_running():
            return

        def run() -> None:
            try:
                print(f"Visual change monologue... score={score:.1f}", flush=True)
                send_visual_change(self.args.server, self.args.playback_device, self.args.no_play, True, score)
            finally:
                self.last_visual_monologue_at = time.monotonic()
                self.reset_visual_watch()

        self.visual_thread = threading.Thread(target=run, daemon=True)
        self.visual_thread.start()

    def maybe_start_visual_monologue(self, button_value: int, now: float) -> None:
        if not self.active or not self.visual_watch_enabled() or self.next_visual_check_at <= 0 or now < self.next_visual_check_at:
            return
        self.next_visual_check_at = now + self.args.visual_watch_interval
        if button_value != 0 or self.recording_process is not None or self.hold_recording_started:
            return
        if self.shutdown_confirming or self.visual_monologue_running():
            return
        if now - self.last_visual_monologue_at < self.args.visual_change_cooldown:
            return

        sample = self.visual_sample()
        if sample is None:
            return
        score = self.visual_change_score(sample)
        if score >= self.args.visual_change_threshold:
            self.start_visual_monologue(score)

    def start_hold_recording(self) -> None:
        if not self.active or self.shutdown_confirming or self.recording_process is not None or self.visual_monologue_running():
            return
        self.reset_visual_watch()
        self.reset_clicks()
        tmpdir = tempfile.TemporaryDirectory()
        # Keep a reference on the object via the process so the directory survives.
        wav_path = Path(tmpdir.name) / "utterance.wav"
        process = start_recording(wav_path, self.args.capture_device, self.args.rate)
        process._primo_tmpdir = tmpdir  # type: ignore[attr-defined]
        self.recording_process = process
        self.recording_path = wav_path
        self.hold_recording_started = True
        start_face("listening", True)
        print("Recording...", flush=True)

    def finish_recording(self) -> None:
        if self.recording_process is None or self.recording_path is None:
            return
        process = self.recording_process
        wav_path = self.recording_path
        stop_recording(process)
        self.recording_process = None
        self.recording_path = None

        duration = time.monotonic() - self.press_started_at
        print(f"Recorded {duration:.1f}s", flush=True)
        if duration < self.args.min_record_seconds or not wav_path.exists() or wav_path.stat().st_size < 1024:
            start_face("idle", True)
            return

        start_face("thinking", True)
        send_and_play(self.args.server, wav_path, self.args.playback_device, self.args.no_play, True)
        tmpdir = getattr(process, "_primo_tmpdir", None)
        if tmpdir is not None:
            tmpdir.cleanup()

    def shutdown_prompt(self) -> dict:
        from urllib.parse import urljoin

        talk_url = urljoin(self.args.server.rstrip("/") + "/", "talk")
        return post_json(talk_url, talk_payload("シャットダウンしますか？", {"source": "shutdown_confirm", "client": "radxa"}))

    def is_yes(self, text: str) -> bool:
        normalized = text.strip().replace(" ", "").replace("　", "")
        yes_words = ("はい", "ハイ", "うん", "ウン", "お願い", "おねがい", "シャットダウンして", "電源切って")
        no_words = ("いいえ", "いや", "やめ", "キャンセル", "しない", "ない", "だめ", "待って")
        return any(word in normalized for word in yes_words) and not any(word in normalized for word in no_words)

    def record_shutdown_answer(self) -> str:
        with tempfile.TemporaryDirectory() as tmp:
            wav_path = Path(tmp) / "shutdown-answer.wav"
            start_face("listening", True, "シャットダウンしますか？", "はい、と言うとシャットダウンします。")
            process = start_recording(wav_path, self.args.capture_device, self.args.rate)
            time.sleep(self.args.shutdown_answer_seconds)
            stop_recording(process)
            if not wav_path.exists() or wav_path.stat().st_size < 1024:
                return ""
            start_face("thinking", True, "シャットダウンしますか？", "")
            return transcribe_audio(self.args.server, wav_path)

    def request_shutdown_confirmation(self) -> None:
        if self.shutdown_confirming:
            return
        was_active = self.active
        self.shutdown_confirming = True
        self.cancel_recording()
        self.reset_visual_watch(clear_sample=True)
        print("Shutdown confirmation requested", flush=True)
        try:
            if not was_active:
                console_mode("mascot")
            start_face("thinking", True, "確認", "シャットダウンしますか？")
            try:
                reply = self.shutdown_prompt()
                display_and_play_reply(reply, "確認", self.args.playback_device, self.args.no_play, True, clear_after=False)
            except Exception as exc:
                print(f"shutdown prompt failed: {exc}", flush=True)
                start_face("idle", True, "確認", "シャットダウンしますか？ はい、と言うとシャットダウンします。")

            answer = self.record_shutdown_answer()
            print(f"shutdown answer: {answer}", flush=True)
            if self.is_yes(answer):
                start_face("speaking", True, "確認", "シャットダウンします。")
                subprocess.Popen(["sudo", "-n", "/sbin/shutdown", "-h", "now"])
                return

            start_face("idle", True, "確認", "シャットダウンしません。")
            time.sleep(1.5)
        finally:
            self.shutdown_confirming = False
            self.reset_clicks()
            if was_active:
                start_face("idle", True)
                self.reset_visual_watch()
            else:
                stop_face()
                stop_camera()
                console_mode("console")

    def handle_release(self) -> None:
        now = time.monotonic()
        press_duration = now - self.press_started_at

        if self.hold_recording_started:
            self.finish_recording()
            self.reset_clicks()
            return

        if press_duration <= self.args.click_max_seconds:
            if self.click_count and now > self.click_deadline:
                self.reset_clicks()
            self.click_count += 1
            self.click_deadline = now + self.args.multi_click_seconds
            if self.click_count >= 3:
                self.reset_clicks()
                self.request_shutdown_confirmation()

    def maybe_finish_click_sequence(self, now: float) -> None:
        if self.click_count == 0 or now < self.click_deadline:
            return
        count = self.click_count
        self.reset_clicks()
        if count == 2:
            self.toggle()

    def run(self) -> None:
        self.initialize_state()
        previous = 0
        reader_context = gpio_value_reader(self.args.gpio_chip, self.args.gpio_line)
        read_value = next(reader_context)
        try:
            while True:
                value = read_value()
                now = time.monotonic()

                if value != previous:
                    previous = value
                    if value == 1:
                        self.press_started_at = now
                        self.hold_recording_started = False
                        self.reset_visual_watch()
                    else:
                        self.handle_release()

                if (
                    self.active
                    and value == 1
                    and not self.hold_recording_started
                    and now - self.press_started_at >= self.args.hold_to_record_seconds
                ):
                    self.start_hold_recording()

                if value == 0:
                    self.maybe_finish_click_sequence(now)
                self.maybe_start_visual_monologue(value, now)
                time.sleep(0.01)
        finally:
            self.cancel_recording()
            stop_face()
            stop_camera()
            try:
                next(reader_context)
            except StopIteration:
                pass


def main() -> None:
    parser = argparse.ArgumentParser(description="Always-on Primo-tan button supervisor.")
    parser.add_argument("--server", required=True)
    parser.add_argument("--gpio-chip", type=int, default=3)
    parser.add_argument("--gpio-line", type=int, default=1)
    parser.add_argument("--capture-device", default="plughw:CARD=wm8960soundcard,DEV=0")
    parser.add_argument("--playback-device", default="plughw:CARD=wm8960soundcard,DEV=0")
    parser.add_argument("--rate", type=int, default=16000)
    parser.add_argument("--hold-to-record-seconds", type=float, default=0.45)
    parser.add_argument("--min-record-seconds", type=float, default=0.6)
    parser.add_argument("--click-max-seconds", type=float, default=0.32)
    parser.add_argument("--multi-click-seconds", type=float, default=0.65)
    parser.add_argument("--shutdown-answer-seconds", type=float, default=3.0)
    parser.add_argument("--visual-watch-interval", type=float, default=2.0)
    parser.add_argument("--visual-change-threshold", type=float, default=18.0)
    parser.add_argument("--visual-change-cooldown", type=float, default=90.0)
    parser.add_argument("--no-visual-watch", action="store_true")
    parser.add_argument("--monologue-min-seconds", type=float, default=0.0, help=argparse.SUPPRESS)
    parser.add_argument("--monologue-max-seconds", type=float, default=0.0, help=argparse.SUPPRESS)
    parser.add_argument("--no-monologue", dest="no_visual_watch", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--start-inactive", dest="start_active", action="store_false")
    parser.add_argument("--no-play", action="store_true")
    parser.set_defaults(start_active=True)
    args = parser.parse_args()

    try:
        PrimoSupervisor(args).run()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
