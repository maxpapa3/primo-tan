#!/usr/bin/env python3
"""Radxa-side client for the Mac mini mascot bridge."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen


def post_json(url: str, payload: dict) -> dict:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    with urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def download(url: str, destination: Path) -> None:
    with urlopen(url, timeout=60) as response:
        destination.write_bytes(response.read())


def play_audio(path: Path) -> None:
    players = [
        ["aplay", str(path)],
        ["paplay", str(path)],
        ["ffplay", "-nodisp", "-autoexit", str(path)],
    ]
    for command in players:
        try:
            subprocess.run(command, check=True)
            return
        except FileNotFoundError:
            continue
        except subprocess.CalledProcessError:
            continue
    print(f"audio saved but no player succeeded: {path}", file=sys.stderr)


def render_text(reply: dict) -> None:
    emotion = reply.get("emotion", "neutral")
    text = reply.get("text", "")
    print(f"[{emotion}] {text}")
    if reply.get("audio_url"):
        print(f"audio: {reply['audio_url']}")


def run_once(server: str, text: str, play: bool) -> int:
    talk_url = urljoin(server.rstrip("/") + "/", "talk")
    try:
        reply = post_json(talk_url, {"text": text, "meta": {"client": "radxa"}})
    except HTTPError as exc:
        print(f"server returned HTTP {exc.code}", file=sys.stderr)
        return 1
    except URLError as exc:
        print(f"cannot reach server: {exc.reason}", file=sys.stderr)
        return 1

    if not reply.get("ok", False):
        print(json.dumps(reply, ensure_ascii=False), file=sys.stderr)
        return 1

    render_text(reply)

    audio_url = reply.get("audio_url")
    if play and audio_url:
        with tempfile.TemporaryDirectory() as tmp:
            audio_path = Path(tmp) / "reply.wav"
            download(str(audio_url), audio_path)
            play_audio(audio_path)

    return 0


def interactive(server: str, play: bool) -> int:
    print("Type text and press Enter. Ctrl-D to quit.")
    for line in sys.stdin:
        text = line.strip()
        if not text:
            continue
        code = run_once(server, text, play)
        if code != 0:
            return code
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Talk to the Mac mini mascot bridge.")
    parser.add_argument("--server", required=True, help="Example: http://<mac-mini-ip>:8765")
    parser.add_argument("--text", help="Send one text utterance and exit.")
    parser.add_argument("--no-play", action="store_true", help="Do not play returned audio.")
    args = parser.parse_args()

    play = not args.no_play
    if args.text is not None:
        raise SystemExit(run_once(args.server, args.text, play))
    raise SystemExit(interactive(args.server, play))


if __name__ == "__main__":
    main()
