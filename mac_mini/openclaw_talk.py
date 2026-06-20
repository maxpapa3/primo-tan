#!/usr/bin/env python3
"""Adapter from the mascot bridge JSON stdin contract to fast OpenClaw inference."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any


OPENCLAW = os.environ.get("OPENCLAW_BIN", "openclaw")
SESSION_KEY = os.environ.get("OPENCLAW_MASCOT_SESSION_KEY", "agent:main:radxa-mascot")
MODEL = os.environ.get("OPENCLAW_MASCOT_MODEL", "openai/gpt-5.4-mini")
THINKING = os.environ.get("OPENCLAW_MASCOT_THINKING", "off")
BACKEND = os.environ.get("OPENCLAW_MASCOT_BACKEND", "infer").lower()
TIMEOUT = int(os.environ.get("OPENCLAW_MASCOT_TIMEOUT", "180"))
AUDIO_DIR = Path(__file__).resolve().parent / "audio"


def read_payload() -> dict[str, Any]:
    raw = sys.stdin.read().strip()
    if not raw:
        return {}
    return json.loads(raw)


def extract_json(stdout: str) -> dict[str, Any]:
    start = stdout.find("{")
    end = stdout.rfind("}")
    if start < 0 or end < start:
        raise ValueError("OpenClaw did not return JSON")
    return json.loads(stdout[start : end + 1])


def extract_text(result: dict[str, Any]) -> str:
    outputs = result.get("outputs", [])
    if outputs and isinstance(outputs[0], dict):
        text = outputs[0].get("text")
        if text:
            return str(text)

    payloads = result.get("result", {}).get("payloads", [])
    if payloads and isinstance(payloads[0], dict):
        text = payloads[0].get("text")
        if text:
            return str(text)

    meta = result.get("result", {}).get("meta", {})
    for key in ("finalAssistantVisibleText", "finalAssistantRawText"):
        text = meta.get(key)
        if text:
            return str(text)

    return "返答を取得できませんでした。"


def image_path_from_payload(payload: dict[str, Any]) -> str | None:
    meta = payload.get("meta", {})
    if not isinstance(meta, dict):
        return None
    image_path = str(meta.get("image_path") or "").strip()
    if image_path and Path(image_path).exists():
        return image_path
    return None


def run_infer(prompt: str, image_path: str | None = None) -> dict[str, Any]:
    command = [
        OPENCLAW,
        "infer",
        "model",
        "run",
        "--model",
        MODEL,
        "--thinking",
        THINKING,
        "--prompt",
        prompt,
        "--json",
    ]
    if image_path:
        command.extend(["--file", image_path])
    completed = subprocess.run(
        command,
        text=True,
        capture_output=True,
        timeout=TIMEOUT,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or completed.stdout.strip() or "OpenClaw infer failed")
    return extract_json(completed.stdout)


def run_agent(prompt: str) -> dict[str, Any]:
    command = [
        OPENCLAW,
        "agent",
        "--session-key",
        SESSION_KEY,
        "--message",
        prompt,
        "--model",
        MODEL,
        "--thinking",
        THINKING,
        "--json",
        "--timeout",
        str(TIMEOUT),
    ]
    completed = subprocess.run(
        command,
        text=True,
        capture_output=True,
        timeout=TIMEOUT + 30,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or completed.stdout.strip() or "OpenClaw agent failed")
    return extract_json(completed.stdout)


def emotion_for(text: str) -> str:
    if any(mark in text for mark in ("！", "!", "嬉", "うれしい", "よかった", "できます")):
        return "happy"
    if any(mark in text for mark in ("すみません", "エラー", "できません", "失敗")):
        return "sad"
    if any(mark in text for mark in ("？", "?")):
        return "curious"
    return "neutral"


def speech_text(text: str) -> str:
    cleaned = re.sub(r"[*_`#>\[\]()]", "", text)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    replacements = {
        "プリモたん": "ぷりもたん",
        "Radxa": "ラドザ",
        "radxa": "ラドザ",
        "Whisplay": "ウィスプレイ",
        "OpenClaw": "オープンクロー",
        "GPT": "ジーピーティー",
        "TTS": "ティーティーエス",
        "STT": "エスティーティー",
        "AI": "エーアイ",
        "WiFi": "ワイファイ",
        "GPIO": "ジーピーアイオー",
    }
    for before, after in replacements.items():
        cleaned = cleaned.replace(before, after)
    return cleaned


def convert_to_wav(source: Path, destination: Path) -> None:
    ffmpeg = os.environ.get("MASCOT_FFMPEG_BIN", "ffmpeg")
    subprocess.run(
        [
            ffmpeg,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(source),
            "-ac",
            "1",
            "-ar",
            os.environ.get("MASCOT_TTS_WAV_RATE", "22050"),
            "-sample_fmt",
            "s16",
            str(destination),
        ],
        check=True,
        timeout=60,
    )


def create_openclaw_tts_audio(spoken_text: str, wav_path: Path) -> None:
    tmp_path = wav_path.with_suffix(".tts")
    command = [
        OPENCLAW,
        "infer",
        "tts",
        "convert",
        "--text",
        spoken_text,
        "--voice",
        os.environ.get("MASCOT_TTS_VOICE", "ja-JP-NanamiNeural"),
        "--output",
        str(tmp_path),
        "--json",
    ]
    model = os.environ.get("MASCOT_TTS_MODEL", "").strip()
    if model:
        command.extend(["--model", model])

    completed = subprocess.run(
        command,
        text=True,
        capture_output=True,
        timeout=float(os.environ.get("MASCOT_TTS_TIMEOUT", "90")),
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or completed.stdout.strip() or "OpenClaw TTS failed")

    if not tmp_path.exists():
        result = extract_json(completed.stdout)
        outputs = result.get("outputs", [])
        if outputs and isinstance(outputs[0], dict) and outputs[0].get("path"):
            tmp_path = Path(str(outputs[0]["path"]))
    if not tmp_path.exists():
        raise RuntimeError("OpenClaw TTS did not create an audio file")

    convert_to_wav(tmp_path, wav_path)
    try:
        tmp_path.unlink()
    except FileNotFoundError:
        pass


def maybe_create_audio(text: str, spoken_text: str) -> str | None:
    tts_backend = os.environ.get("MASCOT_TTS", "").lower()
    if tts_backend not in {"macos_say", "openclaw_tts"}:
        return None

    public_base_url = os.environ.get("MASCOT_PUBLIC_BASE_URL", "").rstrip("/")
    if not public_base_url:
        return None

    AUDIO_DIR.mkdir(exist_ok=True)
    voice = os.environ.get("MASCOT_SAY_VOICE", "Kyoko")
    stem = f"reply-{int(time.time())}-{uuid.uuid4().hex[:8]}"
    aiff_path = AUDIO_DIR / f"{stem}.aiff"
    wav_path = AUDIO_DIR / f"{stem}.wav"

    if tts_backend == "openclaw_tts":
        create_openclaw_tts_audio(spoken_text, wav_path)
    else:
        subprocess.run(["say", "-v", voice, "-o", str(aiff_path), spoken_text], check=True, timeout=60)
        subprocess.run(
            ["afconvert", "-f", "WAVE", "-d", "LEI16@22050", str(aiff_path), str(wav_path)],
            check=True,
            timeout=60,
        )
        try:
            aiff_path.unlink()
        except FileNotFoundError:
            pass

    return f"{public_base_url}/audio/{wav_path.name}"


def main() -> int:
    payload = read_payload()
    user_text = str(payload.get("text", "")).strip()
    if not user_text:
        print(json.dumps({"text": "聞こえませんでした。もう一度お願いします。", "emotion": "confused"}, ensure_ascii=False))
        return 0

    meta = payload.get("meta", {})
    if not isinstance(meta, dict):
        meta = {}
    spontaneous = meta.get("source") == "spontaneous"
    image_path = image_path_from_payload(payload)
    vision_instruction = (
        "この会話にはカメラ画像も添えられています。"
        "画像を見て、見えたものやそこから感じた雰囲気を、断定しすぎず自然に一言だけ混ぜてください。"
        "ユーザーの質問への返答が主役で、映像の感想はさりげなく添えてください。"
        if image_path
        else ""
    )

    persona = (
        "あなたの名前は「プリモたん」です。"
        "あなたは手のひらサイズのコミュニケーションデバイスに住む、やさしいAIマスコットです。"
        "一人称は自然に「プリモたん」または「私」を使ってください。"
        "日本語で、あたたかく自然で短く話してください。"
        "操作説明や内部事情は不要です。"
    )
    if spontaneous:
        prompt = (
            f"{persona}"
            "これはユーザーからの質問ではなく、プリモたんが自分から小さくつぶやく場面です。"
            "今の気分、見えているものから感じたこと、ちょっとした気づきのどれかを、独り言として1文だけ話してください。"
            "ユーザーに返事を求めたり、毎回あいさつしたりしないでください。"
            f"{vision_instruction}\n\n"
            f"きっかけ: {user_text}"
        )
    else:
        prompt = (
            f"{persona}"
            "ユーザーへの返答は1〜2文にしてください。"
            f"{vision_instruction}\n\n"
            f"ユーザー: {user_text}"
        )

    try:
        started = time.monotonic()
        result = run_agent(prompt) if BACKEND == "agent" else run_infer(prompt, image_path)
        text = extract_text(result).strip()
        elapsed = round(time.monotonic() - started, 3)
    except Exception as exc:
        print(
            json.dumps(
                {
                    "text": "OpenClawの返答を読み取れませんでした。",
                    "emotion": "sad",
                    "error": str(exc),
                },
                ensure_ascii=False,
            )
        )
        return 0

    spoken_text = speech_text(text)
    response = {
        "text": text,
        "tts_text": spoken_text,
        "emotion": emotion_for(text),
        "timing": {"llm": elapsed, "backend": BACKEND},
    }
    tts_started = time.monotonic()
    audio_url = maybe_create_audio(text, spoken_text)
    if audio_url:
        response["audio_url"] = audio_url
        response["timing"]["tts"] = round(time.monotonic() - tts_started, 3)
    print(json.dumps(response, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
