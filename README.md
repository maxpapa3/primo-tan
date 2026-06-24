# プリモたん AI Communication Device

Mac miniを頭脳、Radxa Zero 3Wを小型表示・音声端末として使うコミュニケーションデバイス「プリモたん」の実験実装です。
プリモたんは、敬語を使わない幼い女の子のような口調で、短くやわらかく話します。

```text
Telegram / cron / X
        |
Mac mini: mascot_server.py + OpenClaw/LLM/TTS
        |
      WiFi
        |
Radxa Zero 3W: Whisplay LCD/audio/buttons + camera preview
```

## まず動かす

Mac mini側:

```bash
cd /path/to/primo-tan
python3 mac_mini/mascot_server.py --host 0.0.0.0 --port 8765
```

別ターミナルで確認:

```bash
curl -s http://127.0.0.1:8765/health
curl -s -X POST http://127.0.0.1:8765/talk \
  -H 'Content-Type: application/json' \
  -d '{"text":"こんにちは"}'
```

Radxa側:

```bash
scp -r radxa_client radxa@radxa-zero3w.local:~/radxa-ai-mascot
ssh radxa@radxa-zero3w.local
cd ~/radxa-ai-mascot
python3 mascot_client.py --server http://<Mac miniのIP>:8765 --text "こんにちは"
```

Mac miniのIPを再確認する場合:

```bash
ifconfig
```

よく使う値は環境変数で上書きできます。

```bash
export RADXA_HOST=radxa-zero3w.local
export MAC_HOST=<Mac miniのIP>
```

## SSH鍵認証

Radxaへ非対話で配置・実行するため、Mac miniからRadxaへのSSH鍵を使います。

```bash
scripts/setup_radxa_ssh_key.sh
scripts/check_radxa_ssh.sh
scripts/install_radxa_client.sh
```

接続先の例:

```text
Mac mini: <Mac miniのIP>
Radxa:    radxa-zero3w.local
```

## OpenClaw連携

`MASCOT_TALK_COMMAND` を指定すると、`/talk` の入力テキストを標準入力で渡して、そのコマンドの出力を返答として使います。

コマンドの出力は次のどちらにも対応します。

プレーンテキスト:

```text
こんにちは。今日もよろしくお願いします。
```

JSON:

```json
{
  "text": "こんにちは。今日もよろしくお願いします。",
  "emotion": "happy",
  "audio_url": "http://<Mac miniのIP>:8765/audio/reply.wav"
}
```

例:

```bash
export MASCOT_TALK_COMMAND="/path/to/openclaw-talk"
python3 mac_mini/mascot_server.py --host 0.0.0.0 --port 8765
```

OpenClaw CLIが動作している環境では、次のコマンドでOpenClaw接続版サーバを起動できます。

```bash
mac_mini/run_openclaw_server.sh
```

内部では [mac_mini/openclaw_talk.py](mac_mini/openclaw_talk.py) が、会話用に軽い一発推論を実行します。

```bash
openclaw infer model run \
  --model openai/gpt-5.4-mini \
  --thinking off \
  --prompt "..." \
  --json
```

必要なら環境変数で調整できます。

```bash
export OPENCLAW_MASCOT_SESSION_KEY="agent:main:radxa-mascot"
export OPENCLAW_MASCOT_MODEL="openai/gpt-5.4-mini"
export OPENCLAW_MASCOT_BACKEND="infer"
export OPENCLAW_MASCOT_THINKING="off"
export OPENCLAW_MASCOT_TIMEOUT="45"
mac_mini/run_openclaw_server.sh
```

高品質TTSファイルも返す場合:

```bash
export MASCOT_TTS="openclaw_tts"
export MASCOT_TTS_VOICE="ja-JP-NanamiNeural"
export MASCOT_PUBLIC_BASE_URL="http://<Mac miniのIP>:8765"
mac_mini/run_openclaw_server.sh
```

`openclaw_tts` はOpenClawのTTS providerを使って音声を生成し、Radxaの `aplay` で再生できる16bit mono WAVへ変換します。OpenClaw TTSが使えない場合は `MASCOT_TTS=macos_say` と `MASCOT_SAY_VOICE=Kyoko` へ戻せます。

Radxa側で `--no-play` を外すと、返ってきた `audio_url` をダウンロードして再生します。
録音後はまずSTT結果をLCD上部の「質問」に表示し、その後、読み上げ中と読み上げ後の待機画面ではLCD下部の「返答」にAIの返答テキストを表示します。
AIマスコット起動中は、LCD右側にRaspiカメラの最新フレームを小窓表示します。会話時はその最新フレームもMac miniへ送り、プリモたんの返答に映像から感じ取った雰囲気を自然に混ぜます。カメラはデフォルトで `/dev/video0` を使い、必要ならRadxa側サービスの環境変数 `PRIMO_CAMERA_DEVICE` や `PRIMO_CAMERA_ROTATE` で調整できます。

## プリモたんに話しかける

固定秒数録音でまず試す場合:

```bash
ssh -i ~/.ssh/radxa_zero3w_ed25519 radxa@radxa-zero3w.local
cd ~/radxa-ai-mascot
python3 voice_client.py --server http://<Mac miniのIP>:8765 --mode fixed --seconds 4
```

Whisplay HATのボタンを使う場合、Radxa Zero 3WではデフォルトでGPIO `gpiochip3` line `1` を読みます。

```bash
python3 voice_client.py --server http://<Mac miniのIP>:8765 --mode gpio-button
```

常時待ち受けとして起動する場合:

```bash
scripts/setup_radxa_console_mode.sh
scripts/start_radxa_voice_client.sh
scripts/status_radxa_voice_client.sh
```

起動後はWhisplay HATのボタンで操作できます。

```text
ダブルクリック: プリモたんON/OFF切り替え
トリプルクリック: ON/OFFに関わらずシャットダウン確認
ON中に約0.45秒以上長押し: 押している間だけ録音、離すと返答
OFF中: コンソール画面を表示
ON中: コンソールを消してプリモたんの顔だけ表示
```

トリプルクリックすると「シャットダウンしますか？」と聞きます。続けて「はい」と言った場合だけRadxaをシャットダウンします。無言や「いいえ」などの場合はシャットダウンしません。

プリモたんON中は、録音していない間にカメラ画像を常時見ています。映像に一定以上の変化が起きた時だけ、見えたものについて短くつぶやきます。
検知感度や再発話までの待ち時間はRadxa側の `primo_supervisor.py` に渡す引数で調整できます。

```bash
python3 primo_supervisor.py \
  --server http://<Mac miniのIP>:8765 \
  --visual-watch-interval 2 \
  --visual-change-threshold 18 \
  --visual-change-cooldown 90
```

止めたい場合は `--no-visual-watch` を付けます。

停止:

```bash
scripts/stop_radxa_voice_client.sh
```

`setup_radxa_console_mode.sh` は初回だけ実行します。プリモたん起動中はRadxaのfbcon/ttyを `/dev/fb0` から外して顔だけ表示し、停止時にコンソール表示を戻します。

## 顔アニメーション

Radxa側の [radxa_client/face_display.py](radxa_client/face_display.py) が `/dev/fb0` に直接RGB565でプリモたんの顔を描画します。

状態:

```text
idle       待機、瞬き
listening  聞き取り中、青いリング
thinking   考え中、ドット
speaking   発話中、口パクと音量バー
sad        エラー時
```

手動表示テスト:

```bash
ssh -i ~/.ssh/radxa_zero3w_ed25519 radxa@radxa-zero3w.local
cd ~/radxa-ai-mascot
python3 face_display.py --state idle --duration 5
python3 face_display.py --state speaking --duration 5
```

`voice_client.py` はデフォルトで顔アニメーションを使います。無効化する場合は `--no-face` を付けます。

もしGPIOモードで反応しない場合は、`/dev/input` イベントも確認できます。

```bash
cd ~/radxa-ai-mascot
for e in /dev/input/event*; do echo "$e"; timeout 5 python3 button_probe.py "$e"; done
```

押したときに `code=... value=1`、離したときに `value=0` が出る `/dev/input/eventX` と `code` を使います。

```bash
python3 voice_client.py \
  --server http://<Mac miniのIP>:8765 \
  --mode button \
  --event /dev/input/eventX \
  --code CODE
```

音声認識はMac mini側の `~/.radxa-mascot-stt` に入れた `mlx-whisper` を使います。高速化のため、常駐サーバは同じPythonプロセス内で `mlx_whisper` を直接呼び、モデルを温めたまま使います。デフォルトモデルは `mlx-community/whisper-tiny-mlx` です。

## 常駐化

Mac mini起動時にプリモたんAPIを自動起動する場合:

```bash
scripts/install_mascot_launch_agent.sh
```

macOSのDocumentsアクセス制限を避けるため、常駐実行用ファイルは `~/.radxa-mascot` にコピーされます。
コード更新後は、常駐実行用コピーへ反映するためにこのスクリプトを再実行してください。

状態確認:

```bash
scripts/status_mascot_launch_agent.sh
```

Radxa起動時にボタン監視を自動起動する場合:

```bash
scripts/install_radxa_mascot_service.sh
```

このサービスは起動直後はOFF状態で待機します。Whisplay HATのボタンをダブルクリックすると、コンソール画面を消してプリモたんの顔を表示します。

Radxa側の状態確認:

```bash
scripts/status_radxa_voice_client.sh
```

停止・削除:

```bash
scripts/uninstall_mascot_launch_agent.sh
```

ログ:

```text
~/Library/Logs/radxa-mascot/stdout.log
~/Library/Logs/radxa-mascot/stderr.log
```

## License

MIT License. See [LICENSE](LICENSE).
