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
export PIPER_VOICE_PATH="$HOME/.local/share/zvonko/voices/ru_RU-denis-medium.onnx"
if [[ "$TTS_ENGINE" == piper && ! -s "$PIPER_VOICE_PATH" ]]; then
  echo 'V3 voice Denis missing: bash setup-v3-wsl.sh' >&2
  exit 1
fi
echo 'Starting V3. Wait for Connected to local Asterisk ARI, then call 201 in MicroSIP.'
echo 'Original 200 can still run separately. Ctrl+C stops only V3.'
exec .venv/bin/python -u server_v3.py
