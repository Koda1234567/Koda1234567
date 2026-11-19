#!/usr/bin/env bash
# Russian neural Piper voice for local MicroSIP + Asterisk test.
# Does not alter Asterisk, Novofon, Ollama, or SIP credentials.
set -Eeuo pipefail
cd "$(dirname "$0")"
if [[ ! -x .venv/bin/python ]]; then
  echo "Missing .venv. Run install-local-ai-wsl.sh first." >&2
  exit 1
fi
VOICE_DIR="$HOME/.local/share/zvonko/voices"
VOICE_ID="ru_RU-denis-medium"
mkdir -p "$VOICE_DIR"
if [[ -n "${ZVONKO_DOWNLOAD_PROXY:-}" ]]; then
  export HTTPS_PROXY="$ZVONKO_DOWNLOAD_PROXY"
  export HTTP_PROXY="$ZVONKO_DOWNLOAD_PROXY"
  export NO_PROXY="localhost,127.0.0.1,::1"
  export no_proxy="$NO_PROXY"
  echo "Model downloads through configured HTTPS proxy."
fi
echo "=== Installing Piper neural speech runtime ==="
.venv/bin/python -m pip install 'piper-tts>=1.3,<2'
if [[ ! -s "$VOICE_DIR/$VOICE_ID.onnx" || ! -s "$VOICE_DIR/$VOICE_ID.onnx.json" ]]; then
  echo "=== Downloading Russian voice $VOICE_ID ==="
  .venv/bin/python -m piper.download_voices --download-dir "$VOICE_DIR" "$VOICE_ID"
fi
if [[ ! -s "$VOICE_DIR/$VOICE_ID.onnx" || ! -s "$VOICE_DIR/$VOICE_ID.onnx.json" ]]; then
  echo "Voice model or .json not downloaded. No live SIP configuration was changed." >&2
  exit 1
fi
echo "=== Measuring first speech synthesis (local) ==="
PIPER_VOICE_PATH="$VOICE_DIR/$VOICE_ID.onnx" .venv/bin/python - <<'PY'
from pathlib import Path
from piper import PiperVoice
import os, wave, tempfile, time
p=Path(os.environ['PIPER_VOICE_PATH'])
start=time.monotonic()
voice=PiperVoice.load(p,use_cuda=False)
with tempfile.TemporaryFile(mode='w+b') as out:
    with wave.open(out,'wb') as wav:
        voice.synthesize_wav('Здравствуйте! Я Звонко, голосовой помощник.',wav)
    out.seek(0)
    with wave.open(out,'rb') as wav:
        length=wav.getnframes()/wav.getframerate()
        print(f"Voice: {p.name}; audio={length:.2f}s; sample rate={wav.getframerate()}Hz; ready in {time.monotonic()-start:.2f}s")
print('PIPER READY')
PY
echo "Voice installed. Stop current engine with Ctrl+C, run git pull, then bash start-local-ai-wsl.sh."
