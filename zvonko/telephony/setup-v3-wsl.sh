#!/usr/bin/env bash
# Install separate local Zvonko v3 SIP extension 201; preserve original 200.
set -Eeuo pipefail
umask 077
cd "$(dirname "$0")"
DIAL=/etc/asterisk/extensions.conf
ENV_FILE="$HOME/.config/zvonko/ai.env"
VOICE_DIR="$HOME/.local/share/zvonko/voices"
MODEL="$(printenv OLLAMA_MODEL_V3 || echo qwen3:4b)"
if [[ ! -f "$ENV_FILE" || ! -x .venv/bin/python ]]; then
  echo 'Existing local AI setup missing; do not reinstall Asterisk.' >&2
  exit 1
fi
if ! curl --noproxy '*' --fail --silent --max-time 3 http://127.0.0.1:11434/api/tags >/dev/null; then
  echo 'Start Ollama with sudo systemctl start ollama' >&2
  exit 1
fi
if [[ ! -x .venv/bin/python ]]; then
  echo 'Python environment missing.' >&2
  exit 1
fi
VOICE_ID=ru_RU-denis-medium
if [[ ! -s "$VOICE_DIR/$VOICE_ID.onnx" || ! -s "$VOICE_DIR/$VOICE_ID.onnx.json" ]]; then
  if [[ -n "$(printenv ZVONKO_DOWNLOAD_PROXY || true)" ]]; then
    export HTTPS_PROXY="$ZVONKO_DOWNLOAD_PROXY"
    export HTTP_PROXY="$ZVONKO_DOWNLOAD_PROXY"
    export NO_PROXY='localhost,127.0.0.1,::1'
  fi
  mkdir -p "$VOICE_DIR"
  echo "=== Downloading alternative Russian voice $VOICE_ID ==="
  .venv/bin/python -m piper.download_voices --download-dir "$VOICE_DIR" "$VOICE_ID"
fi
if [[ ! -s "$VOICE_DIR/$VOICE_ID.onnx" || ! -s "$VOICE_DIR/$VOICE_ID.onnx.json" ]]; then
  echo 'Alternative voice not downloaded; 200 untouched.' >&2
  exit 1
fi
echo "=== Pulling stronger language model $MODEL ==="
ollama pull "$MODEL"
sudo -v
if ! sudo test -f "$DIAL"; then
  echo "Asterisk dialplan missing: $DIAL" >&2
  exit 1
fi
echo '=== Adding independent local 201 test route; 200 unchanged ==='
sudo cp -p "$DIAL" "$DIAL.before-zvonko-v3"
sudo python3 - "$DIAL" <<'PY'
from pathlib import Path
import re,sys
p=Path(sys.argv[1]); s=p.read_text()
pat=r'(?ms)^\[zvonko-localtest\]\s*\n.*?(?=^\[[^\]]+\]\s*$|\Z)'
matches=list(re.finditer(pat,s))
if len(matches)!=1:
    raise SystemExit('Expected exactly one [zvonko-localtest] context; refusing edit.')
m=matches[0]; block=m.group()
if not re.search(r'(?m)^exten\s*=>\s*200,',block):
    raise SystemExit('Original 200 route not found; refusing edit.')
if re.search(r'(?m)^exten\s*=>\s*201,',block):
    if 'Stasis(zvonko3,inbound)' in block:
        print('V3 route 201 already installed; no changes.')
        raise SystemExit(0)
    raise SystemExit('201 already belongs to another route; refusing overwrite.')
addon=(
    '\n; Isolated Zvonko 3 local test, no outbound calls.\n'
    'exten => 201,1,NoOp(Zvonko v3 trial)\n'
    ' same => n,Answer()\n'
    ' same => n,Stasis(zvonko3,inbound)\n'
    ' same => n,Hangup()\n'
)
p.write_text(s[:m.end()]+addon+s[m.end():])
print('Extension 201 registered; original extension 200 untouched.')
PY
sudo asterisk -rx 'dialplan reload'
sudo asterisk -rx 'dialplan show 201@zvonko-localtest'
echo 'V3 route ready. Run bash start-v3-wsl.sh, then call 201 in MicroSIP.'
