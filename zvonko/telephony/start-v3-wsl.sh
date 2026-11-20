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
# V3 trial uses ONLY free local Ekaterina. Never silently revert to Denis.
# The installer verifies actual Russian synthesis before creating the marker.
SILERO_MODEL_PATH="$HOME/.local/share/zvonko/voices/v5_cis_base_nostress.jit"
SILERO_READY="$HOME/.local/share/zvonko/voices/v5_cis_base_nostress.ready"
if [[ ! -s "$SILERO_MODEL_PATH" || ! -s "$SILERO_READY" ]]; then
  echo 'ERROR: Ekaterina voice is NOT installed/verified. Refusing to start with Denis.' >&2
  echo 'Download/verify it first: bash install-silero-v3-wsl.sh' >&2
  echo 'If official download times out, download v5_cis_base_nostress.jit in Windows browser and use ZVONKO_LOCAL_SILERO_FILE=/mnt/c/.../v5_cis_base_nostress.jit.' >&2
  exit 1
fi
export TTS_ENGINE=silero
export SILERO_MODEL_PATH
export SILERO_SPEAKER=ru_ekaterina
echo 'Zvonko V3 voice: Silero ru_ekaterina. Denis/Piper disabled.'
echo 'Starting V3. Wait for Connected to local Asterisk ARI, then call 201 in MicroSIP.'
echo 'Original 200 can still run separately. Ctrl+C stops only V3.'
exec .venv/bin/python -u server_v3.py
