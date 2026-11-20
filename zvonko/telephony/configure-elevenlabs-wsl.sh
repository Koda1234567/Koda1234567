#!/usr/bin/env bash
# Optional paid cloud voice. Never send credentials to chat, GitHub or logs.
set -Eeuo pipefail
umask 077
ENV_FILE="$HOME/.config/zvonko/ai.env"
if [[ ! -f "$ENV_FILE" ]]; then
  echo 'Local Zvonko environment not found; complete setup first.' >&2
  exit 1
fi
echo 'ElevenLabs sends the AI-generated TEXT response to an external provider.'
echo 'Provider may charge for speech. Review privacy terms and your plan.'
read -r -p 'Enable this optional external TTS? Type YES: ' CONSENT
if [[ "$CONSENT" != YES ]]; then
  echo 'Cloud voice not enabled.'; exit 0
fi
read -r -p 'ElevenLabs voice ID (from voice library): ' VOICE_ID
if [[ ! "$VOICE_ID" =~ ^[A-Za-z0-9]{16,64}$ ]]; then
  echo 'Invalid voice ID; changes cancelled.' >&2; exit 1
fi
read -rs -p 'ElevenLabs API key (hidden, do not paste into chat): ' API_KEY
echo
if [[ "$API_KEY" == "" || "$API_KEY" =~ ^.{0,15}$ ]]; then
  echo 'API key too short; changes cancelled.' >&2; exit 1
fi
export NEW_VOICE_ID="$VOICE_ID"
export NEW_API_KEY="$API_KEY"
python3 - "$ENV_FILE" <<'PY'
import os,shlex,sys
from pathlib import Path
dest=Path(sys.argv[1])
changes={
  'ELEVENLABS_VOICE_ID':os.environ['NEW_VOICE_ID'],
  'ELEVENLABS_API_KEY':os.environ['NEW_API_KEY'],
  'ELEVENLABS_MODEL':'eleven_flash_v2_5',
  'ALLOW_CLOUD_TTS':'true',
}
existing=dest.read_text(encoding='utf-8').splitlines()
rows=[line for line in existing if not any(
    line.startswith('export '+k+'=') for k in changes)]
rows += ['export '+k+'='+shlex.quote(v) for k,v in changes.items()]
dest.write_text('\n'.join(rows)+'\n',encoding='utf-8')
dest.chmod(0o600)
print('Private cloud voice settings saved; secrets not displayed.')
PY
unset NEW_API_KEY API_KEY NEW_VOICE_ID
echo 'Cloud voice: ZVONKO_VOICE_BACKEND=elevenlabs bash start-v3-wsl.sh'
echo 'Fully local: bash start-v3-wsl.sh'
