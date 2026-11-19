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
export OLLAMA_MODEL_V3="$(printenv OLLAMA_MODEL_V3 || echo qwen2.5:3b)"
export TTS_ENGINE=piper
echo 'Starting V3. Wait for Connected to local Asterisk ARI, then call 201 in MicroSIP.'
echo 'Original 200 can still run separately. Ctrl+C stops only V3.'
exec .venv/bin/python -u server_v3.py
