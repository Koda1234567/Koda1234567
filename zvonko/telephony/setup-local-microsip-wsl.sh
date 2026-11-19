#!/usr/bin/env bash
# Zvonko local-only MicroSIP -> Asterisk audio test on Windows 11 WSL2 mirrored.
# No Novofon, no public phone number, no payment, no outgoing dialling.
set -Eeuo pipefail
umask 077
MAIN=/etc/asterisk/pjsip.conf
DIAL=/etc/asterisk/extensions.conf
FRAGMENT=/etc/asterisk/pjsip_zvonko_local.conf
CREDENTIALS="$HOME/.config/zvonko/local-sip.txt"
sudo -v
if [[ "$(wslinfo --networking-mode 2>/dev/null || true)" != mirrored ]]; then
  echo 'Enable WSL2 mirrored networking first. This script does not modify Windows.' >&2
  exit 1
fi
if ! sudo test -f "$MAIN" || ! sudo test -f "$DIAL"; then
  echo 'Missing Asterisk configuration; install Asterisk first.' >&2
  exit 1
fi
if ! sudo grep -q '^\[zvonko-udp\]' "$MAIN"; then
  echo 'Expected existing [zvonko-udp] transport; refusing to change unknown configuration.' >&2
  exit 1
fi
if sudo test -e "$FRAGMENT" || sudo grep -Fq '#include pjsip_zvonko_local.conf' "$MAIN" || sudo grep -q '^\[zvonko-localtest\]' "$DIAL"; then
  echo 'Local test was already configured. No changes made.' >&2
  echo 'Check: sudo asterisk -rx "pjsip show endpoints"'
  exit 0
fi
if sudo grep -Fq '^' /dev/null; then :; fi
if ! sudo grep -q '^bind=0\.0\.0\.0:5060$' "$MAIN" && ! sudo grep -q '^bind=127\.0\.0\.1:5060$' "$MAIN"; then
  echo 'Transport bind differs from expected 0.0.0.0:5060 or 127.0.0.1:5060.' >&2
  exit 1
fi
PASSWORD="$(openssl rand -hex 20)"
TMP="$(mktemp)"
trap 'rm -f "$TMP"; unset PASSWORD' EXIT
cat >"$TMP" <<EOF
; Separate LOCAL account: independent of the Novofon SIP line.
[zvonko-localtest]
type=endpoint
transport=zvonko-udp
context=zvonko-localtest
disallow=all
allow=alaw,ulaw
auth=zvonko-localtest-auth
aors=zvonko-localtest
direct_media=no
force_rport=yes
rewrite_contact=yes
rtp_symmetric=yes
identify_by=username,auth_username

[zvonko-localtest-auth]
type=auth
auth_type=userpass
username=zvonko-localtest
password=$PASSWORD

[zvonko-localtest]
type=aor
max_contacts=1
remove_existing=yes
qualify_frequency=30
EOF
sudo cp -p "$MAIN" "$MAIN.before-zvonko-local"
sudo cp -p "$DIAL" "$DIAL.before-zvonko-local"
sudo install -m 0640 -o root -g asterisk "$TMP" "$FRAGMENT"
# WSL mirrored makes Windows->WSL 127.0.0.1 available: restrict SIP transport to loopback.
sudo sed -i 's/^bind=0\.0\.0\.0:5060$/bind=127.0.0.1:5060/' "$MAIN"
# Suspend the operator trunk during the purely local test, leaving credentials untouched.
sudo sed -i 's/^#include pjsip_zvonko.conf$/;#include pjsip_zvonko.conf ; disabled during local pilot/' "$MAIN"
printf '\n#include pjsip_zvonko_local.conf\n' | sudo tee -a "$MAIN" >/dev/null
cat <<'DIALPLAN' | sudo tee -a "$DIAL" >/dev/null

; Local test only, MicroSIP -> Asterisk, no Novofon or public calling.
[zvonko-localtest]
exten => 200,1,NoOp(Zvonko local call audio test)
 same => n,Answer()
 same => n,Wait(1)
 same => n,Playback(beep)
 same => n,Echo()
 same => n,Hangup()
DIALPLAN
mkdir -p "$(dirname "$CREDENTIALS")"
{
  echo 'ZVONKO LOCAL - PRIVATELY STORED ACCOUNT - DO NOT SHARE SCREENSHOT'
  echo 'SIP Server: 127.0.0.1:5060'
  echo 'SIP Proxy: (empty)'
  echo 'Domain: 127.0.0.1'
  echo 'Username: zvonko-localtest'
  echo 'Login: zvonko-localtest'
  echo "Password: $PASSWORD"
  echo 'Transport: UDP'
  echo 'Public Address: Auto'
  echo 'Call extension: 200'
} >"$CREDENTIALS"
chmod 0600 "$CREDENTIALS"
unset PASSWORD
sudo systemctl restart asterisk
echo '=== Zvonko local-only SIP endpoint ==='
sudo asterisk -rx 'pjsip show endpoint zvonko-localtest'
echo '=== Local dialplan ==='
sudo asterisk -rx 'dialplan show zvonko-localtest'
echo
echo "Account fields are stored privately: $CREDENTIALS"
echo "To view locally: cat $CREDENTIALS (do not share a screenshot showing Password)."
echo 'Create a NEW MicroSIP account with these fields; keep the old Novofon account saved but inactive.'
echo 'Once MicroSIP shows Online, dial 200. Hear beep/echo: confirms audio, NOT the AI yet.'
