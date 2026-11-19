#!/usr/bin/env bash
# Run interactive local AI voice bridge in the current WSL terminal.
# Keep terminal open while manually calling extension 200 in MicroSIP.
set -Eeuo pipefail
cd "$(dirname "$0")"
ENV_FILE="$HOME/.config/zvonko/ai.env"
if [[ ! -f "$ENV_FILE" ]]; then
 echo 'Run enable-local-ai-wsl.sh first; no private AI environment found' >&2
 exit 1
fi
if [[ ! -x .venv/bin/python ]]; then
 echo 'Python venv missing: run install-local-ai-wsl.sh first' >&2; exit 1
fi
if ! curl --fail --silent --max-time 3 http://127.0.0.1:11434/api/tags >/dev/null; then
 echo 'Ollama offline: sudo systemctl start ollama' >&2; exit 1
fi
set -a
# Written exclusively by enable-local-ai-wsl.sh; shell-quoted values, mode 0600.
source "$ENV_FILE"
set +a
echo 'Starting Zvonko voice engine; no calls will be originated automatically.'
echo 'Wait for "Connected to local Asterisk ARI", then manually call 200 from MicroSIP.'
echo 'Ctrl+C stops voice engine; SIP line is still available.'
exec .venv/bin/python -u server.py
