#!/usr/bin/env bash
set -euo pipefail

payload="$(cat)"
text="$(printf '%s' "${payload}" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("text", ""))')"

python3 -c 'import json,sys; text=sys.argv[1]; print(json.dumps({"text": f"OpenClaw接続テストです。入力は「{text}」でした。", "emotion": "happy"}, ensure_ascii=False))' "${text}"
