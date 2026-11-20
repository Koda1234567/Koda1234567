#!/usr/bin/env bash
# Local Zvonko v3 server: separate ARI app and health port from original 200.
set -Eeuo pipefail
cd "$(dirname "$0")"
ENV_FILE="$HOME/.config/zvonko/ai.env"
if [[ ! -f "$ENV_FILE" || ! -x .venv/bin/python ]]; then
  echo 'Local AI installation missing: complete the previous setup first.' >&2
  exit 1
fi
if ! curl --noproxy '*' --fail --silent --max-time 3 http://127.0.0.1:11434/api/tags >/dev/null; then
  echo 'Ollama offline: sudo systemctl start ollama' >&2
  exit 1
fi
set -a
source "$ENV_FILE"
set +a
export OLLAMA_MODEL_V3="$(printenv OLLAMA_MODEL_V3 || echo qwen3.5:4b)"
# Optional premium cloud voice is disabled by default and requires explicit
# authorization + a private key in ~/.config/zvonko/ai.env.
export TTS_ENGINE="${ZVONKO_VOICE_BACKEND:-piper}"
if [[ "$TTS_ENGINE" == elevenlabs ]]; then
  if [[ "${ALLOW_CLOUD_TTS:-false}" != true ]]; then
    echo 'Cloud voice not authorized. Run bash configure-elevenlabs-wsl.sh' >&2; exit 1
  fi
  echo 'Cloud ElevenLabs voice enabled: AI reply TEXT leaves the computer.'
fi
# Private, independently selected voice for the v3 trial. Never modify the
# shared ai.env: extension 200 can keep its existing TTS configuration.
VOICE_FILE="$HOME/.config/zvonko/v3-voice"
V3_PIPER_VOICE="${ZVONKO_V3_PIPER_VOICE:-}"
if [[ -z "$V3_PIPER_VOICE" && -f "$VOICE_FILE" ]]; then
  IFS= read -r V3_PIPER_VOICE < "$VOICE_FILE" || true
fi
V3_PIPER_VOICE="${V3_PIPER_VOICE:-denis}"
case "$V3_PIPER_VOICE" in
  denis|dmitri|irina|ruslan) ;;
  *) echo 'Invalid v3 Piper voice. Allowed: denis, dmitri, irina, ruslan.' >&2; exit 1 ;;
esac
export PIPER_VOICE_PATH="$HOME/.local/share/zvonko/voices/ru_RU-$V3_PIPER_VOICE-medium.onnx"
if [[ "$TTS_ENGINE" == piper && ( ! -s "$PIPER_VOICE_PATH" || ! -s "$PIPER_VOICE_PATH.json" ) ]]; then
  echo "V3 Piper $V3_PIPER_VOICE not installed: bash select-v3-voice-wsl.sh $V3_PIPER_VOICE" >&2
  exit 1
fi
if [[ "$TTS_ENGINE" == piper ]]; then
  echo "V3 local voice: $V3_PIPER_VOICE"
fi
echo 'Starting V3. Wait for Connected to local Asterisk ARI, then call 201 in MicroSIP.'
echo 'Original 200 can still run separately. Ctrl+C stops only V3.'
exec .venv/bin/python -u server_v3.py
