#!/usr/bin/env bash
# One-time setup: dedicated Novofon SIP login 0157367 (extension 200).
# Does not modify the existing softphone login 0157329 (extension 100).
set -Eeuo pipefail
umask 077
LOGIN=0157367
MAIN=/etc/asterisk/pjsip.conf
FRAGMENT=/etc/asterisk/pjsip_zvonko.conf
if [[ ! -f "$MAIN" ]]; then echo 'pjsip.conf not found' >&2; exit 1; fi
# Asterisk config is root/asterisk-readable, not readable by an ordinary WSL user.
# Elevate before checking it; no SIP password is needed at this point.
sudo -v
if ! sudo grep -q '^\[zvonko-udp\]' "$MAIN"; then
  echo 'Existing [zvonko-udp] transport missing. Do not proceed.' >&2
  exit 1
fi
if [[ -e "$FRAGMENT" ]] || sudo grep -Fq '#include pjsip_zvonko.conf' "$MAIN"; then
  echo 'A Novofon fragment is already configured; refusing to overwrite.' >&2
  exit 1
fi
read -r -s -p 'Введите SIP-пароль робота 0157367 (не старой линии): ' SIP_PASSWORD
printf '\n'
if [[ -z "$SIP_PASSWORD" || "$SIP_PASSWORD" == *';'* || "$SIP_PASSWORD" == *'#'* ]]; then
 echo 'Invalid password character or empty password. Nothing changed.' >&2
 exit 1
fi
TEMP=$(mktemp)
trap 'rm -f "$TEMP"; unset SIP_PASSWORD' EXIT
cat > "$TEMP" <<EOF
; Private SIP credentials; never push this file to GitHub
[novofon-zvonko-registration]
type=registration
transport=zvonko-udp
outbound_auth=novofon-zvonko-auth
server_uri=sip:sip.novofon.ru:5060
client_uri=sip:$LOGIN@sip.novofon.ru
contact_user=$LOGIN
retry_interval=60
expiration=120

[novofon-zvonko-auth]
type=auth
auth_type=userpass
username=$LOGIN
password=$SIP_PASSWORD

[novofon-zvonko-aor]
type=aor
contact=sip:sip.novofon.ru:5060

[mytrunk]
type=endpoint
transport=zvonko-udp
context=zvonko-inbound
disallow=all
allow=alaw,ulaw
outbound_auth=novofon-zvonko-auth
aors=novofon-zvonko-aor
from_user=$LOGIN
from_domain=sip.novofon.ru
direct_media=no
force_rport=yes
rewrite_contact=yes
rtp_symmetric=yes

[novofon-zvonko-identify]
type=identify
endpoint=mytrunk
match=sip.novofon.ru
EOF
unset SIP_PASSWORD
sudo cp -p "$MAIN" "$MAIN.before-zvonko"
sudo install -o root -g asterisk -m 0640 "$TEMP" "$FRAGMENT"
printf '\n#include pjsip_zvonko.conf\n' | sudo tee -a "$MAIN" >/dev/null
sudo systemctl restart asterisk
echo 'SIP registration status:'
sudo asterisk -rx 'pjsip show registrations'
echo 'Registered means signaling only; media, NAT, and AI voice still need a real call test.'
