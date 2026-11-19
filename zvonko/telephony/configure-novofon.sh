#!/usr/bin/env bash
# Run on NEW dedicated Ubuntu VPS after install-ubuntu.sh.
# Secrets entered only in the VPS terminal, never in GitHub or Cloudflare.
set -Eeuo pipefail
if [[ $EUID -ne 0 ]]; then echo 'Run with sudo' >&2; exit 1; fi
if [[ ! -e /opt/zvonko/server.py || ! -e /etc/asterisk/ari.conf ]]; then
 echo 'Run install-ubuntu.sh first' >&2; exit 1
fi
if [[ ! -f asterisk/pjsip.conf.example || ! -f asterisk/extensions.conf ]]; then
 echo 'Run from zvonko/telephony directory' >&2; exit 1
fi
if [[ -f /etc/zvonko-configured.flag ]]; then
 echo 'Already configured; refusing to overwrite SIP credentials.' >&2; exit 1
fi
read -r -p 'New SEPARATE Novofon robot SIP login (not your existing softphone): ' LOGIN
if [[ ! $LOGIN =~ ^[0-9]{5,15}$ || $LOGIN == '0157329' ]]; then
 echo 'Invalid or existing softphone login. Create another SIP account.' >&2; exit 1
fi
read -rs -p 'Robot SIP password (hidden): ' SIP_PASSWORD
echo
if [[ $SIP_PASSWORD == *';'* || $SIP_PASSWORD == *'#'* || $SIP_PASSWORD == *$'\n'* || $SIP_PASSWORD == *$'\r'* || -z $SIP_PASSWORD ]]; then
 echo 'Password contains unsupported configuration characters.' >&2; exit 1
fi
trap 'unset SIP_PASSWORD' EXIT
ARI_PASSWORD=$(openssl rand -hex 32)
ADMIN_TOKEN=$(openssl rand -hex 32)
export LOGIN SIP_PASSWORD ARI_PASSWORD ADMIN_TOKEN
umask 077
python3 - <<'PY'
from pathlib import Path
import os
base=Path('asterisk')
pjsip=(base/'pjsip.conf.example').read_text()
pjsip=pjsip.replace('REPLACE_SIP_LOGIN',os.environ['LOGIN']).replace(
    'REPLACE_SIP_PASSWORD',os.environ['SIP_PASSWORD'])
Path('/etc/asterisk/pjsip.conf').write_text(pjsip)
ari=(base/'ari.conf').read_text().replace(
    'REPLACE_LONG_RANDOM_SECRET',os.environ['ARI_PASSWORD'])
Path('/etc/asterisk/ari.conf').write_text(ari)
for name in ('http.conf','extensions.conf'):
    Path('/etc/asterisk/'+name).write_text((base/name).read_text())
env=(Path('.env.example').read_text()
 .replace('REPLACE_LONG_RANDOM_SECRET',os.environ['ARI_PASSWORD'])
 .replace('REPLACE_RANDOM_32_BYTES',os.environ['ADMIN_TOKEN']))
Path('/etc/zvonko.env').write_text(env)
PY
chown root:asterisk /etc/asterisk/{pjsip,ari,http,extensions}.conf
chmod 0640 /etc/asterisk/{pjsip,ari,http,extensions}.conf
chown root:root /etc/zvonko.env
chmod 0600 /etc/zvonko.env
install -m 0600 /dev/null /etc/zvonko-configured.flag
systemctl restart asterisk
echo 'SIP account written to Asterisk (no calls placed).'
echo 'Verify: sudo asterisk -rx "pjsip show registrations"'
echo 'Only after Registered: install Ollama, Qwen and Russian speech models.'
