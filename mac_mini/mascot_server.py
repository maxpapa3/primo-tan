#!/usr/bin/env python3
"""Small HTTP bridge for a Radxa-based AI mascot."""

from __future__ import annotations

import argparse
import base64
import contextlib
import importlib
import io
import json
import os
import subprocess
import tempfile
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote


ROOT = Path(__file__).resolve().parent
AUDIO_DIR = ROOT / "audio"
IMAGE_DIR = ROOT / "images"
DEFAULT_STT_BIN = str(Path.home() / ".radxa-mascot-stt/bin/mlx_whisper")
DEFAULT_STT_MODEL = "mlx-community/whisper-tiny-mlx"
MLX_WHISPER: Any | None = None


def json_response(handler: BaseHTTPRequestHandler, status: int, payload: dict[str, Any]) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def read_json(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    length = int(handler.headers.get("Content-Length", "0"))
    if length <= 0:
        return {}
    raw = handler.rfile.read(length)
    return json.loads(raw.decode("utf-8"))


def run_talk_command(text: str, meta: dict[str, Any]) -> dict[str, Any] | None:
    command = os.environ.get("MASCOT_TALK_COMMAND")
    if not command:
        return None

    payload = json.dumps({"text": text, "meta": meta}, ensure_ascii=False)
    completed = subprocess.run(
        command,
        input=payload,
        text=True,
        shell=True,
        capture_output=True,
        timeout=float(os.environ.get("MASCOT_TALK_TIMEOUT", "60")),
        check=False,
    )
    if completed.returncode != 0:
        return {
            "text": "会話処理でエラーが出ました。ログを確認してください。",
            "emotion": "sad",
            "error": completed.stderr.strip(),
        }

    output = completed.stdout.strip()
    if not output:
        return {"text": "返答が空でした。", "emotion": "neutral"}

    try:
        parsed = json.loads(output)
        if isinstance(parsed, dict):
            return normalize_reply(parsed)
    except json.JSONDecodeError:
        pass

    return {"text": output, "emotion": "happy"}


def save_image_payload(payload: dict[str, Any], meta: dict[str, Any]) -> None:
    image_b64 = payload.get("image_b64")
    if not isinstance(image_b64, str) or not image_b64.strip():
        return

    try:
        raw = base64.b64decode(image_b64, validate=True)
    except Exception:
        return
    if not raw:
        return

    IMAGE_DIR.mkdir(exist_ok=True)
    image_path = IMAGE_DIR / f"camera-{int(time.time())}.jpg"
    image_path.write_bytes(raw)
    meta["image_path"] = str(image_path)


def normalize_reply(reply: dict[str, Any]) -> dict[str, Any]:
    text = str(reply.get("text") or reply.get("reply") or "")
    emotion = str(reply.get("emotion") or "neutral")
    normalized = {"text": text, "emotion": emotion}

    for key in ("audio_url", "audio_path", "mouth", "timing", "tts_text"):
        if key in reply:
            normalized[key] = reply[key]

    if not normalized["text"]:
        normalized["text"] = "返答テキストがありませんでした。"
    return normalized


def fallback_reply(text: str) -> dict[str, Any]:
    if not text.strip():
        return {"text": "聞こえませんでした。もう一度お願いします。", "emotion": "confused"}
    return {
        "text": f"受け取りました: {text}",
        "emotion": "happy",
    }


def transcribe_audio(path: Path) -> str:
    command = os.environ.get("MASCOT_STT_COMMAND")
    if command:
        completed = subprocess.run(
            command,
            input=str(path),
            text=True,
            shell=True,
            capture_output=True,
            timeout=float(os.environ.get("MASCOT_STT_TIMEOUT", "120")),
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(completed.stderr.strip() or completed.stdout.strip() or "STT command failed")
        return completed.stdout.strip()

    direct_mode = os.environ.get("MASCOT_STT_DIRECT", "auto").lower()
    if direct_mode != "off":
        try:
            return transcribe_audio_direct(path)
        except ImportError:
            if direct_mode == "on":
                raise

    stt_bin = os.environ.get("MASCOT_STT_BIN", DEFAULT_STT_BIN)
    if not Path(stt_bin).exists():
        raise RuntimeError("No STT command configured and mlx_whisper was not found")

    with tempfile.TemporaryDirectory() as tmp:
        output_dir = Path(tmp)
        completed = subprocess.run(
            [
                stt_bin,
                str(path),
                "--model",
                os.environ.get("MASCOT_STT_MODEL", DEFAULT_STT_MODEL),
                "--language",
                os.environ.get("MASCOT_STT_LANGUAGE", "ja"),
                "--output-format",
                "txt",
                "--output-dir",
                str(output_dir),
                "--verbose",
                "False",
            ],
            text=True,
            capture_output=True,
            timeout=float(os.environ.get("MASCOT_STT_TIMEOUT", "120")),
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(completed.stderr.strip() or completed.stdout.strip() or "mlx_whisper failed")

        transcript_path = output_dir / f"{path.stem}.txt"
        if transcript_path.exists():
            return clean_transcript(transcript_path.read_text(encoding="utf-8"))
        return clean_transcript(completed.stdout)


def transcribe_audio_direct(path: Path) -> str:
    global MLX_WHISPER
    if MLX_WHISPER is None:
        MLX_WHISPER = importlib.import_module("mlx_whisper")

    stdout = io.StringIO()
    stderr = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        result = MLX_WHISPER.transcribe(
            str(path),
            path_or_hf_repo=os.environ.get("MASCOT_STT_MODEL", DEFAULT_STT_MODEL),
            language=os.environ.get("MASCOT_STT_LANGUAGE", "ja"),
            verbose=False,
            condition_on_previous_text=False,
            no_speech_threshold=float(os.environ.get("MASCOT_STT_NO_SPEECH_THRESHOLD", "0.6")),
        )
    if isinstance(result, dict):
        return clean_transcript(str(result.get("text", "")))
    return clean_transcript(str(result))


def clean_transcript(text: str) -> str:
    transcript = " ".join(text.replace("\n", " ").split()).strip()
    if not transcript:
        return ""

    noise_phrases = {
        "ご視聴ありがとうございました",
        "ご清聴ありがとうございました",
        "ありがとうございました",
        "お疲れ様でした",
    }
    if transcript in noise_phrases:
        return ""

    # Whisper tiny/small can hallucinate one short phrase repeatedly on noisy silence.
    compact = transcript.replace(" ", "").replace("、", "").replace("。", "")
    if len(compact) > 40:
        for size in range(3, min(12, len(compact) // 3) + 1):
            chunk = compact[:size]
            if chunk and compact.startswith(chunk * 3):
                repeated = chunk * (len(compact) // len(chunk))
                if compact.startswith(repeated[: len(compact) - size]):
                    return ""
    return transcript


def add_timing(reply: dict[str, Any], **values: float) -> dict[str, Any]:
    timing = reply.get("timing")
    if not isinstance(timing, dict):
        timing = {}
    for key, value in values.items():
        timing[key] = round(value, 3)
    reply["timing"] = timing
    return reply


class MascotHandler(BaseHTTPRequestHandler):
    server_version = "MascotBridge/0.1"

    def log_message(self, fmt: str, *args: Any) -> None:
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{timestamp}] {self.address_string()} {fmt % args}")

    def do_GET(self) -> None:
        if self.path == "/health":
            json_response(self, 200, {"ok": True, "service": "mascot-bridge"})
            return

        if self.path.startswith("/audio/"):
            self.serve_audio(self.path.removeprefix("/audio/"))
            return

        json_response(self, 404, {"ok": False, "error": "not found"})

    def do_POST(self) -> None:
        if self.path == "/transcribe-audio":
            self.handle_transcribe_audio()
            return

        if self.path == "/talk-audio":
            self.handle_talk_audio()
            return

        if self.path != "/talk":
            json_response(self, 404, {"ok": False, "error": "not found"})
            return

        try:
            payload = read_json(self)
            text = str(payload.get("text", ""))
            meta = payload.get("meta", {})
            if not isinstance(meta, dict):
                meta = {}
            save_image_payload(payload, meta)

            started = time.monotonic()
            reply = run_talk_command(text, meta) or fallback_reply(text)
            add_timing(reply, total=time.monotonic() - started)
            json_response(self, 200, {"ok": True, **normalize_reply(reply)})
        except json.JSONDecodeError:
            json_response(self, 400, {"ok": False, "error": "invalid json"})
        except subprocess.TimeoutExpired:
            json_response(self, 504, {"ok": False, "error": "talk command timed out"})
        except Exception as exc:
            json_response(self, 500, {"ok": False, "error": str(exc)})

    def save_audio_upload(self) -> Path | None:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return None

        AUDIO_DIR.mkdir(exist_ok=True)
        upload_path = AUDIO_DIR / f"upload-{int(time.time())}.wav"
        upload_path.write_bytes(self.rfile.read(length))
        return upload_path

    def handle_transcribe_audio(self) -> None:
        try:
            upload_path = self.save_audio_upload()
            if upload_path is None:
                json_response(self, 400, {"ok": False, "error": "empty audio body"})
                return

            started = time.monotonic()
            transcript = transcribe_audio(upload_path)
            json_response(
                self,
                200,
                {
                    "ok": True,
                    "transcript": transcript,
                    "audio_path": str(upload_path),
                    "timing": {"stt": round(time.monotonic() - started, 3)},
                },
            )
        except subprocess.TimeoutExpired:
            json_response(self, 504, {"ok": False, "error": "speech recognition timed out"})
        except Exception as exc:
            json_response(self, 500, {"ok": False, "error": str(exc)})

    def handle_talk_audio(self) -> None:
        try:
            upload_path = self.save_audio_upload()
            if upload_path is None:
                json_response(self, 400, {"ok": False, "error": "empty audio body"})
                return

            started = time.monotonic()
            stt_started = time.monotonic()
            transcript = transcribe_audio(upload_path)
            stt_elapsed = time.monotonic() - stt_started
            if not transcript:
                json_response(
                    self,
                    200,
                    {
                        "ok": True,
                        "transcript": "",
                        "text": "聞き取れませんでした。もう一度お願いします。",
                        "emotion": "confused",
                        "timing": {"stt": round(stt_elapsed, 3), "total": round(time.monotonic() - started, 3)},
                    },
                )
                return

            talk_started = time.monotonic()
            reply = run_talk_command(transcript, {"source": "audio", "audio_path": str(upload_path)}) or fallback_reply(transcript)
            add_timing(reply, stt=stt_elapsed, talk=time.monotonic() - talk_started, total=time.monotonic() - started)
            json_response(self, 200, {"ok": True, "transcript": transcript, **normalize_reply(reply)})
        except subprocess.TimeoutExpired:
            json_response(self, 504, {"ok": False, "error": "speech recognition timed out"})
        except Exception as exc:
            json_response(self, 500, {"ok": False, "error": str(exc)})

    def serve_audio(self, name: str) -> None:
        AUDIO_DIR.mkdir(exist_ok=True)
        path = (AUDIO_DIR / unquote(name)).resolve()
        if AUDIO_DIR.resolve() not in path.parents or not path.exists():
            json_response(self, 404, {"ok": False, "error": "audio not found"})
            return

        content_type = "audio/wav" if path.suffix.lower() == ".wav" else "application/octet-stream"
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Mac mini mascot bridge API.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    AUDIO_DIR.mkdir(exist_ok=True)
    IMAGE_DIR.mkdir(exist_ok=True)
    server = ThreadingHTTPServer((args.host, args.port), MascotHandler)
    print(f"mascot bridge listening on http://{args.host}:{args.port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
