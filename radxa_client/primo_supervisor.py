#!/usr/bin/env python3
"""Always-on button supervisor for Primo-tan.

Double-click toggles mascot mode. While active, holding the button records speech.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from voice_client import (
    gpio_value_reader,
    send_and_play,
    start_face,
    start_recording,
    stop_camera,
    stop_face,
    stop_recording,
)


def console_mode(mode: str) -> None:
    subprocess.run(["sudo", "-n", "/usr/local/sbin/primo-console-mode", mode], check=False)


class PrimoSupervisor:
    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.active = bool(args.start_active)
        self.last_short_click_at = 0.0
        self.recording_process: subprocess.Popen | None = None
        self.recording_path: Path | None = None
        self.press_started_at = 0.0
        self.hold_recording_started = False

    def set_active(self, active: bool) -> None:
        if self.active == active:
            return
        self.active = active
        if active:
            print("Primo-tan ON", flush=True)
            console_mode("mascot")
            start_face("idle", True)
        else:
            print("Primo-tan OFF", flush=True)
            self.cancel_recording()
            stop_face()
            stop_camera()
            console_mode("console")

    def initialize_state(self) -> None:
        if self.active:
            console_mode("mascot")
            start_face("idle", True)
            print("Primo-tan ON", flush=True)
        else:
            stop_face()
            console_mode("console")
            print("Primo-tan OFF", flush=True)

    def toggle(self) -> None:
        self.set_active(not self.active)

    def cancel_recording(self) -> None:
        if self.recording_process is not None:
            stop_recording(self.recording_process)
        self.recording_process = None
        self.recording_path = None
        self.hold_recording_started = False

    def start_hold_recording(self) -> None:
        if not self.active or self.recording_process is not None:
            return
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

    def handle_release(self) -> None:
        now = time.monotonic()
        press_duration = now - self.press_started_at

        if self.hold_recording_started:
            self.finish_recording()
            self.last_short_click_at = 0.0
            return

        if press_duration <= self.args.click_max_seconds:
            if now - self.last_short_click_at <= self.args.double_click_seconds:
                self.last_short_click_at = 0.0
                self.toggle()
            else:
                self.last_short_click_at = now

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
                    else:
                        self.handle_release()

                if (
                    self.active
                    and value == 1
                    and not self.hold_recording_started
                    and now - self.press_started_at >= self.args.hold_to_record_seconds
                ):
                    self.start_hold_recording()

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
    parser.add_argument("--double-click-seconds", type=float, default=0.65)
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
