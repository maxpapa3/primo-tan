#!/usr/bin/env python3
"""Animated assistant face renderer for /dev/fb0 RGB565 framebuffers."""

from __future__ import annotations

import argparse
import math
import os
import signal
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont


FB_PATH = Path("/dev/fb0")
FB_SYS = Path("/sys/class/graphics/fb0")


def read_fb_info() -> tuple[int, int, int, int]:
    width, height = 280, 240
    bpp = 16
    stride = width * 2

    try:
        raw_width, raw_height = (FB_SYS / "virtual_size").read_text().strip().split(",", 1)
        width, height = int(raw_width), int(raw_height)
    except Exception:
        pass

    try:
        bpp = int((FB_SYS / "bits_per_pixel").read_text().strip())
    except Exception:
        pass

    try:
        stride = int((FB_SYS / "stride").read_text().strip())
    except Exception:
        stride = width * (bpp // 8)

    if bpp != 16:
        raise RuntimeError(f"Only RGB565 16bpp framebuffers are supported; got {bpp}bpp")
    return width, height, bpp, stride


def rgb565_bytes(image: Image.Image, stride: int) -> bytes:
    rgb = np.asarray(image.convert("RGB"), dtype=np.uint16)
    r = rgb[:, :, 0]
    g = rgb[:, :, 1]
    b = rgb[:, :, 2]
    packed = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
    raw = packed.astype("<u2").tobytes()
    row_bytes = image.width * 2
    if stride == row_bytes:
        return raw

    rows = []
    pad = b"\x00" * max(0, stride - row_bytes)
    for y in range(image.height):
        start = y * row_bytes
        rows.append(raw[start : start + row_bytes] + pad)
    return b"".join(rows)


def write_frame(image: Image.Image, fb_path: Path = FB_PATH) -> None:
    width, height, _, stride = read_fb_info()
    if image.size != (width, height):
        image = image.resize((width, height), Image.Resampling.LANCZOS)
    data = rgb565_bytes(image, stride)
    with fb_path.open("r+b", buffering=0) as fb:
        fb.write(data)


def ellipse(draw: ImageDraw.ImageDraw, box, fill, outline=None, width=1):
    draw.ellipse(tuple(map(int, box)), fill=fill, outline=outline, width=width)


def rounded_rectangle(draw: ImageDraw.ImageDraw, box, radius, fill, outline=None, width=1):
    draw.rounded_rectangle(tuple(map(int, box)), radius=int(radius), fill=fill, outline=outline, width=width)


def line(draw: ImageDraw.ImageDraw, points, fill, width=1):
    draw.line([(int(x), int(y)) for x, y in points], fill=fill, width=int(width), joint="curve")


def load_font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    candidates = [
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc" if bold else "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            pass
    return ImageFont.load_default()


def wrap_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_width: int, max_lines: int) -> list[str]:
    normalized = " ".join(text.replace("\n", " ").split())
    if not normalized:
        return []

    lines: list[str] = []
    current = ""
    for char in normalized:
        candidate = current + char
        if draw.textlength(candidate, font=font) <= max_width or not current:
            current = candidate
            continue
        lines.append(current)
        current = char
        if len(lines) >= max_lines:
            break

    if len(lines) < max_lines and current:
        lines.append(current)

    if len(lines) > max_lines:
        lines = lines[:max_lines]

    if lines and draw.textlength(lines[-1], font=font) > max_width:
        while lines[-1] and draw.textlength(lines[-1] + "…", font=font) > max_width:
            lines[-1] = lines[-1][:-1]
        lines[-1] += "…"
    elif len("".join(lines)) < len(normalized):
        while lines[-1] and draw.textlength(lines[-1] + "…", font=font) > max_width:
            lines[-1] = lines[-1][:-1]
        lines[-1] += "…"
    return lines


def draw_text_panel(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    label: str,
    text: str,
    scale: int,
    accent: tuple[int, int, int],
) -> None:
    if not text.strip():
        return

    x1, y1, x2, y2 = box
    rounded_rectangle(draw, box, 8 * scale, (255, 255, 255), (222, 224, 238), width=1 * scale)
    rounded_rectangle(draw, (x1, y1, x1 + 7 * scale, y2), 4 * scale, accent)

    label_font = load_font(8 * scale, bold=True)
    text_font = load_font(10 * scale)
    draw.text((x1 + 13 * scale, y1 + 4 * scale), label, fill=(92, 96, 128), font=label_font)

    max_width = x2 - x1 - 24 * scale
    line_height = 13 * scale
    max_lines = max(1, (y2 - y1 - 21 * scale) // line_height)
    lines = wrap_text(draw, text, text_font, max_width, max_lines)
    for index, line_text in enumerate(lines):
        draw.text((x1 + 13 * scale, y1 + (18 + index * 13) * scale), line_text, fill=(32, 34, 48), font=text_font)


def fit_cover(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    target_w, target_h = size
    src_w, src_h = image.size
    scale = max(target_w / src_w, target_h / src_h)
    new_size = (max(1, int(src_w * scale)), max(1, int(src_h * scale)))
    resized = image.resize(new_size, Image.Resampling.LANCZOS)
    left = max(0, (resized.width - target_w) // 2)
    top = max(0, (resized.height - target_h) // 2)
    return resized.crop((left, top, left + target_w, top + target_h))


def draw_camera_panel(canvas: Image.Image, camera_image: str | None, scale: int) -> None:
    if not camera_image:
        return

    draw = ImageDraw.Draw(canvas)
    w, _ = canvas.size
    x1 = w - 103 * scale
    y1 = 70 * scale
    x2 = w - 7 * scale
    y2 = 151 * scale
    rounded_rectangle(draw, (x1, y1, x2, y2), 8 * scale, (255, 255, 255), (210, 216, 232), width=1 * scale)
    try:
        preview = Image.open(camera_image).convert("RGB")
        preview = fit_cover(preview, (x2 - x1 - 8 * scale, y2 - y1 - 21 * scale))
        canvas.paste(preview, (x1 + 4 * scale, y1 + 16 * scale))
    except Exception:
        font = load_font(9 * scale, bold=True)
        draw.text((x1 + 10 * scale, y1 + 33 * scale), "CAM", fill=(120, 126, 150), font=font)

    label_font = load_font(7 * scale, bold=True)
    draw.text((x1 + 7 * scale, y1 + 4 * scale), "カメラ", fill=(75, 84, 116), font=label_font)


def draw_text_overlay(canvas: Image.Image, question: str | None, answer: str | None, scale: int) -> None:
    if not question and not answer:
        return
    draw = ImageDraw.Draw(canvas)
    w, h = canvas.size
    margin = 7 * scale
    if question:
        draw_text_panel(draw, (margin, margin, w - margin, 62 * scale), "質問", question, scale, (96, 175, 240))
    if answer:
        draw_text_panel(
            draw,
            (margin, h - 69 * scale, w - margin, h - 7 * scale),
            "返答",
            answer,
            scale,
            (245, 110, 135),
        )


def draw_face(
    width: int,
    height: int,
    state: str,
    phase: float,
    question: str | None = None,
    answer: str | None = None,
    camera_image: str | None = None,
) -> Image.Image:
    scale = 3
    canvas = Image.new("RGB", (width * scale, height * scale), (248, 246, 252))
    draw = ImageDraw.Draw(canvas)

    w = width * scale
    h = height * scale
    cx = w / 2 - (34 * scale if camera_image else 0)
    cy = h / 2

    # Dark blue stage-like background.
    for y in range(h):
        t = y / max(1, h - 1)
        r = int(18 * (1 - t) + 42 * t)
        g = int(24 * (1 - t) + 32 * t)
        b = int(48 * (1 - t) + 78 * t)
        draw.line([(0, y), (w, y)], fill=(r, g, b))
    for i in range(18):
        sx = int((i * 37 + 19) % max(1, w))
        sy = int((i * 53 + 31) % max(1, h))
        ellipse(draw, (sx - 1 * scale, sy - 1 * scale, sx + 1 * scale, sy + 1 * scale), (58, 92, 132))

    pulse = 0.5 + 0.5 * math.sin(phase * math.tau)
    bob = math.sin(phase * math.tau) * 5 * scale
    blink = state == "idle" and (phase % 1.0) > 0.88

    if state == "listening":
        ring_color = (115, 190, 255)
        for i in range(3):
            radius = (72 + i * 11 + pulse * 5) * scale
            ellipse(
                draw,
                (cx - radius, cy - radius, cx + radius, cy + radius),
                fill=None,
                outline=tuple(min(255, c + i * 20) for c in ring_color),
                width=2 * scale,
            )
    elif state == "thinking":
        for i in range(3):
            dot_x = cx - 28 * scale + i * 28 * scale
            dot_y = 30 * scale + math.sin((phase + i * 0.18) * math.tau) * 5 * scale
            ellipse(draw, (dot_x - 5 * scale, dot_y - 5 * scale, dot_x + 5 * scale, dot_y + 5 * scale), (115, 125, 180))
    elif state == "speaking":
        for i in range(7):
            bar_h = (10 + 18 * abs(math.sin((phase + i * 0.11) * math.tau))) * scale
            x = (22 + i * 9) * scale
            rounded_rectangle(draw, (x, h - 24 * scale - bar_h, x + 4 * scale, h - 24 * scale), 2 * scale, (120, 205, 235))

    # Shoulders, black jacket, and white shirt.
    rounded_rectangle(draw, (cx - 82 * scale, cy + 52 * scale, cx + 82 * scale, h + 18 * scale), 28 * scale, (10, 13, 24))
    draw.polygon(
        [
            (cx - 51 * scale, cy + 54 * scale),
            (cx - 13 * scale, h + 12 * scale),
            (cx, cy + 77 * scale),
            (cx + 13 * scale, h + 12 * scale),
            (cx + 51 * scale, cy + 54 * scale),
        ],
        fill=(229, 234, 246),
    )
    draw.polygon([(cx - 50 * scale, cy + 55 * scale), (cx - 12 * scale, cy + 93 * scale), (cx - 6 * scale, h + 20 * scale)], fill=(15, 18, 30))
    draw.polygon([(cx + 50 * scale, cy + 55 * scale), (cx + 12 * scale, cy + 93 * scale), (cx + 6 * scale, h + 20 * scale)], fill=(15, 18, 30))

    # Hair silhouette and long side strands.
    hair_shadow = (8, 10, 21)
    hair_mid = (20, 24, 44)
    hair_light = (61, 82, 128)
    ellipse(draw, (cx - 74 * scale, cy - 101 * scale + bob, cx + 74 * scale, cy + 46 * scale + bob), hair_shadow)
    draw.polygon(
        [
            (cx - 75 * scale, cy - 62 * scale + bob),
            (cx - 114 * scale, cy + 8 * scale),
            (cx - 96 * scale, cy + 121 * scale),
            (cx - 48 * scale, cy + 46 * scale + bob),
        ],
        fill=hair_mid,
    )
    draw.polygon(
        [
            (cx + 64 * scale, cy - 65 * scale + bob),
            (cx + 105 * scale, cy + 18 * scale),
            (cx + 90 * scale, cy + 116 * scale),
            (cx + 42 * scale, cy + 42 * scale + bob),
        ],
        fill=hair_mid,
    )

    # Face.
    ellipse(draw, (cx - 51 * scale, cy - 62 * scale + bob, cx + 51 * scale, cy + 54 * scale + bob), (225, 211, 221))

    # Bangs drawn over the face.
    draw.polygon(
        [
            (cx - 67 * scale, cy - 84 * scale + bob),
            (cx - 21 * scale, cy - 64 * scale + bob),
            (cx - 45 * scale, cy - 4 * scale + bob),
            (cx - 80 * scale, cy - 14 * scale + bob),
        ],
        fill=hair_shadow,
    )
    draw.polygon(
        [
            (cx - 29 * scale, cy - 77 * scale + bob),
            (cx + 18 * scale, cy - 67 * scale + bob),
            (cx - 4 * scale, cy - 5 * scale + bob),
            (cx - 36 * scale, cy - 18 * scale + bob),
        ],
        fill=(13, 16, 31),
    )
    draw.polygon(
        [
            (cx + 13 * scale, cy - 70 * scale + bob),
            (cx + 60 * scale, cy - 47 * scale + bob),
            (cx + 35 * scale, cy + 6 * scale + bob),
            (cx + 6 * scale, cy - 15 * scale + bob),
        ],
        fill=(16, 19, 35),
    )
    line(draw, [(cx - 62 * scale, cy - 44 * scale + bob), (cx - 99 * scale, cy + 16 * scale), (cx - 94 * scale, cy + 78 * scale)], hair_light, width=1 * scale)
    line(draw, [(cx + 54 * scale, cy - 40 * scale + bob), (cx + 88 * scale, cy + 22 * scale), (cx + 82 * scale, cy + 88 * scale)], hair_light, width=1 * scale)

    # Eyes and brows.
    eye_y = cy - 16 * scale + bob
    for side in (-1, 1):
        ex = cx + side * 24 * scale
        if blink:
            line(draw, [(ex - 15 * scale, eye_y), (ex + 15 * scale, eye_y - 2 * scale)], (31, 35, 54), width=2 * scale)
        else:
            line(draw, [(ex - 16 * scale, eye_y - 3 * scale), (ex + 14 * scale, eye_y - 1 * scale)], (24, 27, 43), width=2 * scale)
            ellipse(draw, (ex - 10 * scale, eye_y - 7 * scale, ex + 10 * scale, eye_y + 9 * scale), (67, 101, 143))
            ellipse(draw, (ex - 5 * scale, eye_y - 4 * scale, ex + 5 * scale, eye_y + 7 * scale), (18, 24, 39))
            ellipse(draw, (ex + 1 * scale, eye_y - 4 * scale, ex + 5 * scale, eye_y), (224, 242, 255))
    brow_y = cy - 37 * scale + bob
    line(draw, [(cx - 42 * scale, brow_y), (cx - 19 * scale, brow_y - 6 * scale)], (27, 30, 47), width=2 * scale)
    line(draw, [(cx + 19 * scale, brow_y - 6 * scale), (cx + 42 * scale, brow_y)], (27, 30, 47), width=2 * scale)

    # Nose and mouth.
    line(draw, [(cx + 2 * scale, cy - 4 * scale + bob), (cx - 2 * scale, cy + 12 * scale + bob)], (168, 141, 153), width=1 * scale)
    mouth_y = cy + 33 * scale + bob
    if state == "speaking":
        mh = (4 + 7 * abs(math.sin(phase * math.tau * 2))) * scale
        ellipse(draw, (cx - 10 * scale, mouth_y - mh / 2, cx + 10 * scale, mouth_y + mh), (94, 28, 48))
    elif state == "sad":
        line(draw, [(cx - 14 * scale, mouth_y + 4 * scale), (cx, mouth_y), (cx + 14 * scale, mouth_y + 4 * scale)], (85, 36, 57), width=2 * scale)
    else:
        line(draw, [(cx - 14 * scale, mouth_y), (cx + 13 * scale, mouth_y - 2 * scale)], (85, 36, 57), width=2 * scale)

    # Blue rose tie.
    rose_x = cx
    rose_y = cy + 82 * scale
    rose_color = (35, 83, 142)
    for i in range(6):
        angle = i * math.tau / 6 + phase * 0.15
        px = rose_x + math.cos(angle) * 7 * scale
        py = rose_y + math.sin(angle) * 5 * scale
        ellipse(draw, (px - 7 * scale, py - 5 * scale, px + 7 * scale, py + 5 * scale), rose_color)
    ellipse(draw, (rose_x - 5 * scale, rose_y - 5 * scale, rose_x + 5 * scale, rose_y + 5 * scale), (23, 43, 86))
    draw.polygon([(cx - 9 * scale, rose_y + 9 * scale), (cx, h + 5 * scale), (cx + 9 * scale, rose_y + 9 * scale)], fill=(11, 14, 28))

    name_font = load_font(10 * scale, bold=True)
    draw.text((12 * scale, h - 23 * scale), "Ado", fill=(116, 178, 245), font=name_font)

    # Status marker.
    status_colors = {
        "idle": (130, 220, 180),
        "listening": (80, 170, 255),
        "thinking": (160, 130, 240),
        "speaking": (245, 110, 135),
        "sad": (150, 160, 180),
    }
    ellipse(draw, (w - 30 * scale, 13 * scale, w - 14 * scale, 29 * scale), status_colors.get(state, (130, 220, 180)))

    draw_camera_panel(canvas, camera_image, scale)
    draw_text_overlay(canvas, question, answer, scale)
    return canvas.resize((width, height), Image.Resampling.LANCZOS)


def animate(state: str, duration: float | None, fps: float, question: str | None, answer: str | None, camera_image: str | None) -> None:
    width, height, _, _ = read_fb_info()
    start = time.monotonic()
    frame = 0
    while True:
        now = time.monotonic()
        if duration is not None and now - start >= duration:
            break
        phase = (frame / max(1.0, fps)) % 1.0
        image = draw_face(width, height, state, phase, question, answer, camera_image)
        write_frame(image)
        frame += 1
        time.sleep(max(0.01, 1.0 / fps))


def main() -> None:
    parser = argparse.ArgumentParser(description="Render animated mascot face to /dev/fb0.")
    parser.add_argument("--state", choices=["idle", "listening", "thinking", "speaking", "sad"], default="idle")
    parser.add_argument("--duration", type=float, help="Seconds to animate. Omit for forever.")
    parser.add_argument("--fps", type=float, default=8)
    parser.add_argument("--question", default="", help="Recognized user question text to show on the LCD.")
    parser.add_argument("--answer", default="", help="Assistant reply text to show on the LCD.")
    parser.add_argument("--camera-image", default="", help="JPEG image path to show as the live camera panel.")
    parser.add_argument("--message", default="", help="Deprecated alias for --answer.")
    parser.add_argument("--speech-text", default="", help="Deprecated alias for --answer.")
    args = parser.parse_args()

    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    answer = args.answer or args.message or args.speech_text
    animate(args.state, args.duration, args.fps, args.question, answer, args.camera_image)


if __name__ == "__main__":
    main()
