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


def draw_plush_eye(draw: ImageDraw.ImageDraw, ex: float, eye_y: float, side: int, scale: int, blink: bool) -> None:
    outline = (13, 18, 34)
    lash = (16, 19, 35)
    iris = (110, 205, 222)
    iris_dark = (48, 116, 154)
    highlight = (230, 252, 255)
    accent = (176, 87, 62)

    if blink:
        line(draw, [(ex - 22 * scale, eye_y), (ex + 21 * scale, eye_y - 2 * scale)], outline, width=3 * scale)
        for i in range(3):
            lx = ex + side * (-8 + i * 8) * scale
            line(draw, [(lx, eye_y), (lx + side * 3 * scale, eye_y + 7 * scale)], lash, width=1 * scale)
        return

    # Angular embroidered eye outline.
    points = [
        (ex - 23 * scale, eye_y - 10 * scale),
        (ex - 7 * scale, eye_y - 17 * scale),
        (ex + 21 * scale, eye_y - 12 * scale),
        (ex + 23 * scale, eye_y + 7 * scale),
        (ex + 9 * scale, eye_y + 17 * scale),
        (ex - 18 * scale, eye_y + 14 * scale),
        (ex - 25 * scale, eye_y - 2 * scale),
    ]
    draw.polygon(points, fill=(216, 235, 239), outline=outline)
    line(draw, points + [points[0]], outline, width=2 * scale)

    # Thick upper eyelid and warm stitch above the eye.
    line(
        draw,
        [
            (ex - 26 * scale, eye_y - 13 * scale),
            (ex - 8 * scale, eye_y - 21 * scale),
            (ex + 24 * scale, eye_y - 14 * scale),
        ],
        lash,
        width=5 * scale,
    )
    line(
        draw,
        [
            (ex - 17 * scale, eye_y - 22 * scale),
            (ex - 3 * scale, eye_y - 25 * scale),
            (ex + 16 * scale, eye_y - 20 * scale),
        ],
        accent,
        width=1 * scale,
    )

    # Large stitched iris.
    ellipse(draw, (ex - 15 * scale, eye_y - 13 * scale, ex + 15 * scale, eye_y + 15 * scale), iris_dark)
    ellipse(draw, (ex - 11 * scale, eye_y - 11 * scale, ex + 11 * scale, eye_y + 12 * scale), iris)
    ellipse(draw, (ex - 3 * scale, eye_y - 8 * scale, ex + 3 * scale, eye_y + 8 * scale), outline)
    ellipse(draw, (ex - 8 * scale, eye_y - 8 * scale, ex - 3 * scale, eye_y - 4 * scale), highlight)
    ellipse(draw, (ex + 5 * scale, eye_y + 5 * scale, ex + 9 * scale, eye_y + 9 * scale), (170, 235, 245))

    # Heavy plush eyelid shadow: makes the eye large but not wide open.
    draw.polygon(
        [
            (ex - 24 * scale, eye_y - 14 * scale),
            (ex - 6 * scale, eye_y - 21 * scale),
            (ex + 23 * scale, eye_y - 14 * scale),
            (ex + 14 * scale, eye_y - 8 * scale),
            (ex - 12 * scale, eye_y - 11 * scale),
        ],
        fill=lash,
    )
    line(draw, [(ex - 22 * scale, eye_y - 8 * scale), (ex + 20 * scale, eye_y - 7 * scale)], lash, width=2 * scale)

    # Lower lashes.
    for offset in (-17, -5, 8, 19):
        lx = ex + offset * scale
        line(draw, [(lx, eye_y + 16 * scale), (lx + side * 4 * scale, eye_y + 24 * scale)], lash, width=1 * scale)


def draw_background_rose(draw: ImageDraw.ImageDraw, cx: float, cy: float, scale: int, alpha: float = 1.0) -> None:
    petal = (int(35 * alpha), int(86 * alpha), int(128 * alpha))
    center = (int(18 * alpha), int(43 * alpha), int(74 * alpha))
    line_color = (int(57 * alpha), int(118 * alpha), int(164 * alpha))
    radius = 8 * scale
    for i in range(7):
        angle = i * math.tau / 7
        px = cx + math.cos(angle) * radius * 0.55
        py = cy + math.sin(angle) * radius * 0.45
        ellipse(draw, (px - 5 * scale, py - 4 * scale, px + 5 * scale, py + 4 * scale), petal)
    ellipse(draw, (cx - 3 * scale, cy - 3 * scale, cx + 3 * scale, cy + 3 * scale), center)
    line(draw, [(cx + 5 * scale, cy + 6 * scale), (cx + 14 * scale, cy + 17 * scale)], line_color, width=1 * scale)
    line(draw, [(cx + 9 * scale, cy + 11 * scale), (cx + 17 * scale, cy + 8 * scale)], line_color, width=1 * scale)


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
    for rx, ry, rose_scale in (
        (34 * scale, 48 * scale, 3),
        (222 * scale, 43 * scale, 3),
        (238 * scale, 166 * scale, 2),
        (42 * scale, 179 * scale, 2),
    ):
        draw_background_rose(draw, rx, ry, rose_scale, alpha=1.0)

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
    hair_shadow = (15, 25, 50)
    hair_mid = (28, 43, 78)
    hair_light = (74, 109, 145)
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
    ellipse(draw, (cx - 53 * scale, cy - 63 * scale + bob, cx + 53 * scale, cy + 55 * scale + bob), (238, 226, 184))

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
        fill=(18, 29, 55),
    )
    draw.polygon(
        [
            (cx + 13 * scale, cy - 70 * scale + bob),
            (cx + 60 * scale, cy - 47 * scale + bob),
            (cx + 35 * scale, cy + 6 * scale + bob),
            (cx + 6 * scale, cy - 15 * scale + bob),
        ],
        fill=(23, 36, 66),
    )
    line(draw, [(cx - 62 * scale, cy - 44 * scale + bob), (cx - 99 * scale, cy + 16 * scale), (cx - 94 * scale, cy + 78 * scale)], hair_light, width=1 * scale)
    line(draw, [(cx + 54 * scale, cy - 40 * scale + bob), (cx + 88 * scale, cy + 22 * scale), (cx + 82 * scale, cy + 88 * scale)], hair_light, width=1 * scale)

    # Large plush-style embroidered eyes and brows.
    eye_y = cy - 13 * scale + bob
    for side in (-1, 1):
        ex = cx + side * 31 * scale
        draw_plush_eye(draw, ex, eye_y, side, scale, blink)
    brow_y = cy - 47 * scale + bob
    line(draw, [(cx - 44 * scale, brow_y), (cx - 20 * scale, brow_y - 7 * scale)], (18, 21, 36), width=2 * scale)
    line(draw, [(cx + 20 * scale, brow_y - 7 * scale), (cx + 44 * scale, brow_y)], (18, 21, 36), width=2 * scale)

    # Nose and mouth.
    line(draw, [(cx + 2 * scale, cy + 3 * scale + bob), (cx - 2 * scale, cy + 17 * scale + bob)], (168, 141, 153), width=1 * scale)
    mouth_y = cy + 41 * scale + bob
    if state == "speaking":
        mh = (4 + 7 * abs(math.sin(phase * math.tau * 2))) * scale
        ellipse(draw, (cx - 10 * scale, mouth_y - mh / 2, cx + 10 * scale, mouth_y + mh), (94, 28, 48))
    elif state == "sad":
        line(draw, [(cx - 12 * scale, mouth_y + 4 * scale), (cx, mouth_y), (cx + 12 * scale, mouth_y + 4 * scale)], (42, 46, 66), width=2 * scale)
    else:
        line(draw, [(cx - 10 * scale, mouth_y), (cx - 3 * scale, mouth_y - 4 * scale), (cx + 8 * scale, mouth_y - 2 * scale)], (42, 46, 66), width=2 * scale)

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
