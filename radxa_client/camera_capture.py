#!/usr/bin/env python3
"""Continuously capture a small camera preview frame for Primo-tan."""

from __future__ import annotations

import argparse
import signal
import sys
import time
from pathlib import Path

import cv2


RUNNING = True


def stop(*_args) -> None:
    global RUNNING
    RUNNING = False


def main() -> int:
    parser = argparse.ArgumentParser(description="Capture Raspberry Pi camera frames through OpenCV/V4L2.")
    parser.add_argument("--device", default="/dev/video0")
    parser.add_argument("--output", default="/tmp/primo-camera/latest.jpg")
    parser.add_argument("--width", type=int, default=640)
    parser.add_argument("--height", type=int, default=480)
    parser.add_argument("--interval", type=float, default=0.25)
    parser.add_argument("--rotate", choices=["0", "90", "180", "270"], default="0")
    parser.add_argument("--quality", type=int, default=82)
    args = parser.parse_args()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)

    cap = cv2.VideoCapture(args.device, cv2.CAP_V4L2)
    if not cap.isOpened():
        print(f"Cannot open camera: {args.device}", file=sys.stderr)
        return 1

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, args.width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, args.height)

    try:
        while RUNNING:
            ok, frame = cap.read()
            if ok and frame is not None:
                if args.rotate == "90":
                    frame = cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
                elif args.rotate == "180":
                    frame = cv2.rotate(frame, cv2.ROTATE_180)
                elif args.rotate == "270":
                    frame = cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)

                tmp = output.with_suffix(".tmp.jpg")
                cv2.imwrite(str(tmp), frame, [int(cv2.IMWRITE_JPEG_QUALITY), args.quality])
                tmp.replace(output)
            time.sleep(max(0.05, args.interval))
    finally:
        cap.release()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
