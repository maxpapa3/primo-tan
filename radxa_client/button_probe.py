#!/usr/bin/env python3
"""Print Linux input key events so the Whisplay button device/code can be identified."""

from __future__ import annotations

import argparse
import select
import struct

EV_KEY = 0x01
EVENT_STRUCT = struct.Struct("llHHI")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("event", nargs="?", default="/dev/input/event0")
    args = parser.parse_args()

    print(f"Listening on {args.event}. Press buttons; Ctrl-C to stop.")
    with open(args.event, "rb", buffering=0) as event_file:
        while True:
            readable, _, _ = select.select([event_file], [], [], 1.0)
            if not readable:
                continue
            data = event_file.read(EVENT_STRUCT.size)
            if len(data) != EVENT_STRUCT.size:
                continue
            sec, usec, event_type, code, value = EVENT_STRUCT.unpack(data)
            if event_type == EV_KEY:
                print(f"{sec}.{usec:06d} code={code} value={value}", flush=True)


if __name__ == "__main__":
    main()

