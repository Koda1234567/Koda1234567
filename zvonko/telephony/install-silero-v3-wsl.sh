#!/usr/bin/env bash
# Install a free offline Silero v5 CIS Base voice for local extension 201.
# The only automatic download source is the official Silero model host.
# If its TLS connection is blocked, a user may supply the official file
# downloaded with their browser. Never modify extension 200 or secrets.
set -Eeuo pipefail
umask 077
cd "$(dirname "$0")"

if [[ ! -x .venv/bin/python || ! -f "$HOME/.config/zvonko/ai.env" ]]; then
  echo 'Local Zvonko installation missing. Complete v3 setup first.' >&2
  exit 1
fi

VOICE_DIR="$HOME/.local/share/zvonko/voices"
MODEL="$VOICE_DIR/v5_cis_base_nostress.jit"
READY_MARKER="$VOICE_DIR/v5_cis_base_nostress.ready"
SOURCE_URL='https://models.silero.ai/models/tts/ru/v5_cis_base_nostress.jit'
mkdir -p "$VOICE_DIR"

if [[ -n "${ZVONKO_DOWNLOAD_PROXY:-}" ]]; then
  export HTTPS_PROXY="$ZVONKO_DOWNLOAD_PROXY"
  export HTTP_PROXY="$ZVONKO_DOWNLOAD_PROXY"
  export NO_PROXY='localhost,127.0.0.1,::1'
  export no_proxy="$NO_PROXY"
  echo "Using configured download proxy for the official voice file."
fi

if ! .venv/bin/python -c 'import torch; assert int(torch.__version__.split(".")[0]) >= 2' >/dev/null 2>&1; then
  echo 'Installing CPU-only PyTorch required by the free local voice...'
  .venv/bin/python -m pip install 'torch>=2,<3' --index-url https://download.pytorch.org/whl/cpu
fi

# A successful synth test is required before creating READY_MARKER.
rm -f "$READY_MARKER"
temp=''
candidate="$MODEL"
if [[ ! -s "$MODEL" ]]; then
  temp="$(mktemp "$VOICE_DIR/.silero.XXXXXXXX")"
  trap 'rm -f "$temp"' EXIT
  candidate="$temp"

  if [[ -n "${ZVONKO_LOCAL_SILERO_FILE:-}" ]]; then
    if [[ ! -r "$ZVONKO_LOCAL_SILERO_FILE" ]]; then
      echo "Local model file cannot be read: $ZVONKO_LOCAL_SILERO_FILE" >&2
      exit 1
    fi
    echo 'Importing the locally supplied official Silero .jit file...'
    cp -- "$ZVONKO_LOCAL_SILERO_FILE" "$temp"
  else
    echo 'Downloading the original free Silero CIS Base model...'
    if ! curl -fL --retry 2 --connect-timeout 20 --max-time 900 \
         "$SOURCE_URL" -o "$temp"; then
      echo >&2 'ERROR: Silero download failed (network/proxy/TLS).'
      echo >&2 "Open this official URL in a Windows browser:"
      echo >&2 "$SOURCE_URL"
      echo >&2 'Then run this script with ZVONKO_LOCAL_SILERO_FILE=/mnt/c/.../v5_cis_base_nostress.jit.'
      echo >&2 'No new voice was activated. Old Piper remains installed.'
      exit 1
    fi
  fi
fi

if [[ ! -s "$candidate" || "$(wc -c < "$candidate")" -lt 1000000 ]]; then
  echo 'The model is incomplete; refusing to activate a broken voice.' >&2
  exit 1
fi

echo 'Verifying the actual local female voice before activation...'
SILERO_MODEL_PATH="$candidate" .venv/bin/python - <<'PY'
import os
from silero_voice import load_silero_model, synthesize_silero_8k
model = load_silero_model(os.environ['SILERO_MODEL_PATH'])
pcm = synthesize_silero_8k(
    model, 'Здравствуйте! Я помощник Звонко. Какую технику вы ищете?',
    'ru_ekaterina')
assert len(pcm) > 8000 and pcm.dtype.name == 'int16', 'Voice generation failed'
print(f'SILERO TEST PASSED: {len(pcm)/8000:.1f} seconds of Russian speech.')
PY

if [[ -n "$temp" ]]; then
  mv -- "$temp" "$MODEL"
  trap - EXIT
fi
printf '%s\n' 'verified' > "$READY_MARKER"
chmod 600 "$READY_MARKER"
echo 'SILERO READY: ru_ekaterina activated for local test extension 201.'
echo 'Restart only the v3 process: bash start-v3-wsl.sh'
