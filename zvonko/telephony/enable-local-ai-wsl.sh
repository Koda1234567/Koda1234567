#!/usr/bin/env bash
# Switch the already-working local MicroSIP -> Asterisk echo call to real AI.
# IMPORTANT: only run AFTER install-local-ai-wsl.sh succeeds.
# WSL2 localhost only. Does not add outbound calling, does not change Novofon.
set -Eeuo pipefail
cd "$(dirname "$0")"
umask 077
MAIN=/etc/asterisk/extensions.conf
HTTP=/etc/asterisk/http.conf
ARI=/etc/asterisk/ari.conf
ENV_FILE="$HOME/.config/zvonko/ai.env"
MARKER="$HOME/.config/zvonko/local-ai-configured"
if [[ ! -x .venv/bin/python ]]; then echo 'Python env absent: run install-local-ai-wsl.sh first' >&2; exit 1; fi
if ! curl --fail --silent --max-time 3 http://127.0.0.1:11434/api/tags >/dev/null; then
  echo 'Ollama not running: sudo systemctl start ollama' >&2; exit 1
fi
if ! ollama list | grep -Fq 'qwen2.5:1.5b'; then
  echo 'Model missing: ollama pull qwen2.5:1.5b' >&2; exit 1
fi
if [[ -e "$MARKER" ]]; then echo 'Local AI config already applied, refusing to overwrite'; exit 0; fi
sudo -v
if ! sudo grep -q '^\[zvonko-localtest\]$' "$MAIN"; then
  echo 'Local MicroSIP dialplan not found; run setup-local-microsip-wsl.sh first' >&2
  exit 1
fi
if sudo grep -q 'Stasis(zvonko,inbound)' "$MAIN"; then
  echo 'Existing AI route found; verify manually, refusing duplicate changes.' >&2
  exit 1
fi
if ! sudo test -e "$HTTP" || ! sudo test -e "$ARI"; then
  echo 'Asterisk HTTP or ARI config missing'; exit 1
fi
sudo cp -p "$HTTP" "$HTTP.before-zvonko-ai"
sudo cp -p "$ARI" "$ARI.before-zvonko-ai"
sudo cp -p "$MAIN" "$MAIN.before-zvonko-ai"
ARI_SECRET="$(openssl rand -hex 32)"
ADMIN_SECRET="$(openssl rand -hex 32)"
TMP1="$(mktemp)"; TMP2="$(mktemp)"
trap 'rm -f "$TMP1" "$TMP2"; unset ARI_SECRET ADMIN_SECRET' EXIT
cat > "$TMP1" <<'HTTP_EOF'
[general]
enabled=yes
bindaddr=127.0.0.1
bindport=8088
HTTP_EOF
cat > "$TMP2" <<EOF
[general]
enabled=yes
pretty=no

[zvonko]
type=user
read_only=no
password=$ARI_SECRET
EOF
mkdir -p "$(dirname "$ENV_FILE")"
export ARI_SECRET ADMIN_SECRET ENV_FILE
python3 - <<'PY'
from pathlib import Path
import os,shlex
values={}
for line in Path('.env.example').read_text().splitlines():
    if not line.strip() or line.lstrip().startswith('#'):continue
    key,sep,value=line.partition('=')
    if sep:values[key]=value
values.update(ARI_PASSWORD=os.environ['ARI_SECRET'],
  ADMIN_TOKEN=os.environ['ADMIN_SECRET'],
  OLLAMA_MODEL='qwen2.5:1.5b',WHISPER_MODEL='tiny',
  ENABLE_TEST_OUTBOUND='false',TEST_NUMBERS='',CALLER_ID='')
dest=Path(os.environ['ENV_FILE'])
with dest.open('w') as f:
    for key,value in values.items():
        f.write('export '+key+'='+shlex.quote(value)+'\n')
dest.chmod(0o600)
print('Private AI environment created (secrets not shown).')
PY
unset ARI_SECRET ADMIN_SECRET
sudo install -m 0644 -o root -g root "$TMP1" "$HTTP"
sudo install -m 0640 -o root -g asterisk "$TMP2" "$ARI"
sudo python3 - "$MAIN" <<'PY'
from pathlib import Path
import re,sys
p=Path(sys.argv[1]);s=p.read_text()
pat=r'(?ms)^\[zvonko-localtest\]\s*\n.*?(?=^\[[^\]]+\]\s*$|\Z)'
matches=list(re.finditer(pat,s))
if len(matches)!=1:raise SystemExit('Expected exactly one [zvonko-localtest] context')
block='''[zvonko-localtest]
exten => 200,1,NoOp(Zvonko local AI inbound call)
 same => n,Answer()
 same => n,Stasis(zvonko,inbound)
 same => n,Hangup()
'''
s=s[:matches[0].start()]+block+s[matches[0].end():]
p.write_text(s)
print('Switched local extension 200 from Echo to Stasis(zvonko,inbound)')
PY
sudo systemctl restart asterisk
sudo asterisk -rx 'dialplan show zvonko-localtest'
sudo asterisk -rx 'http show status'
touch "$MARKER"
echo 'READY: Asterisk localhost ARI configured and route switched to AI.'
echo 'Next run: bash start-local-ai-wsl.sh ; then manually call 200 from MicroSIP.'
echo 'If anything fails, backups are in /etc/asterisk/*.before-zvonko-ai'
