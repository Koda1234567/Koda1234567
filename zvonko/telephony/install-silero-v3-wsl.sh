#!/usr/bin/env bash
# Install a fully free, on-device Russian Silero CIS Base voice for V3 only.
# Model LICENSE_CIS (MIT): https://github.com/snakers4/silero-models
set -Eeuo pipefail
umask 077
cd "$(dirname "$0")"
if [[ ! -x .venv/bin/python || ! -f "$HOME/.config/zvonko/ai.env" ]]; then
  echo 'Install local Zvonko/Asterisk first; shared AI environment not found.' >&2
  exit 1
fi

VOICE_DIR="$HOME/.local/share/zvonko/voices"
MODEL="$VOICE_DIR/v5_cis_base_nostress.jit"
SOURCE_URL='https://models.silero.ai/models/tts/ru/v5_cis_base_nostress.jit'
mkdir -p "$VOICE_DIR"
if [[ -n "${ZVONKO_DOWNLOAD_PROXY:-}" ]]; then
  export HTTPS_PROXY="$ZVONKO_DOWNLOAD_PROXY"
  export HTTP_PROXY="$ZVONKO_DOWNLOAD_PROXY"
  export NO_PROXY='localhost,127.0.0.1,::1'
  export no_proxy="$NO_PROXY"
  echo 'Using configured proxy for Silero model download.'
fi

if ! .venv/bin/python -c 'import torch; assert int(torch.__version__.split(".")[0]) >= 2' >/dev/null 2>&1; then
  echo 'Installing CPU-only PyTorch for the free Silero voice.'
  .venv/bin/python -m pip install 'torch>=2,<3' --index-url https://download.pytorch.org/whl/cpu
fi

if [[ ! -s "$MODEL" ]]; then
  temp="$(mktemp "$VOICE_DIR/.silero.XXXXXXXX")"
  trap 'rm -f "$temp"' EXIT
  echo 'Downloading official Silero v5 CIS Base (MIT) model...'
  curl -fL --retry 2 --connect-timeout 20 --max-time 900 "$SOURCE_URL" -o "$temp"
  if [[ ! -s "$temp" ]] || [[ "$(wc -c < "$temp")" -lt 1000000 ]]; then
    echo 'Incomplete Silero model; original voices unchanged.' >&2
    exit 1
  fi
  mv "$temp" "$MODEL"
  trap - EXIT
fi

echo 'Checking model and first local voice generation...'
SILERO_MODEL_PATH="$MODEL" .venv/bin/python - <<'PY'
import os
from silero_voice import load_silero_model, synthesize_silero_8k
model = load_silero_model(os.environ['SILERO_MODEL_PATH'])
pcm = synthesize_silero_8k(model,
    'Здравствуйте! Я голосовой помощник Звонко. Что вам нужно убрать?',
    'ru_ekaterina')
assert len(pcm) > 8000 and pcm.dtype.name == 'int16', 'Silero voice synthesis failed'
print(f'SILERO READY: generated {len(pcm)/8000:.1f} seconds of local speech.')
PY

echo 'Silero MIT voice is installed for V3; AI config and extension 200 unchanged.'
echo 'Run: bash start-v3-wsl.sh, then call 201 from MicroSIP.'
