#!/usr/bin/env bash
# Choose a verified local Piper voice only for Zvonko v3 / extension 201.
# Does not edit the shared ai.env, Asterisk, SIP, or original v2/extension 200.
set -Eeuo pipefail
umask 077
cd "$(dirname "$0")"

VOICE="${1:-}"
case "$VOICE" in
  denis|dmitri|irina|ruslan) ;;
  *) echo 'Usage: bash select-v3-voice-wsl.sh denis|dmitri|irina|ruslan' >&2; exit 2 ;;
esac

if [[ ! -x .venv/bin/python || ! -f "$HOME/.config/zvonko/ai.env" ]]; then
  echo 'Install the existing local Zvonko setup before selecting a v3 voice.' >&2
  exit 1
fi

VOICE_DIR="$HOME/.local/share/zvonko/voices"
MODEL="$VOICE_DIR/ru_RU-$VOICE-medium.onnx"
mkdir -p "$VOICE_DIR" "$HOME/.config/zvonko"

if [[ ! -s "$MODEL" || ! -s "$MODEL.json" ]]; then
  if [[ -n "${ZVONKO_DOWNLOAD_PROXY:-}" ]]; then
    export HTTPS_PROXY="$ZVONKO_DOWNLOAD_PROXY"
    export HTTP_PROXY="$ZVONKO_DOWNLOAD_PROXY"
    export NO_PROXY='localhost,127.0.0.1,::1'
    export no_proxy="$NO_PROXY"
  fi
  echo "Downloading ru_RU-$VOICE-medium (this changes no existing voice)..."
  .venv/bin/python -m piper.download_voices --download-dir "$VOICE_DIR" "ru_RU-$VOICE-medium"
fi

if [[ ! -s "$MODEL" || ! -s "$MODEL.json" ]]; then
  echo 'Piper voice or its configuration is missing. Selection unchanged.' >&2
  exit 1
fi

# Smoke-test synthesis before saving the choice; leave old 201 setting on failure.
PIPER_VOICE_PATH="$MODEL" .venv/bin/python - <<'PY'
import os
from piper import PiperVoice, SynthesisConfig
voice = PiperVoice.load(os.environ['PIPER_VOICE_PATH'], use_cuda=False)
samples = sum(
    len(chunk.audio_int16_array)
    for chunk in voice.synthesize(
        'Здравствуйте. Подскажите, какая площадь вашего помещения?',
        syn_config=SynthesisConfig(length_scale=0.95),
    )
)
if samples < 16000:
    raise SystemExit('Voice synthesis test produced too little audio')
print('Local Russian voice synthesis test passed.')
PY

CHOICE_FILE="$HOME/.config/zvonko/v3-voice"
printf '%s\n' "$VOICE" > "$CHOICE_FILE"
chmod 600 "$CHOICE_FILE"
echo "Saved: Zvonko v3 / extension 201 will use Piper $VOICE."
echo 'Restart only v3: bash start-v3-wsl.sh (extension 200 stays unchanged).'
