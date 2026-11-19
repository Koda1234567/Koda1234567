#!/usr/bin/env bash
# Non-destructive dialplan for a real incoming-call RTP test, NOT the AI voice.
# Existing Novofon employee 100 is untouched.
set -Eeuo pipefail
DIALPLAN=/etc/asterisk/extensions.conf
sudo -v
if ! sudo test -f "$DIALPLAN"; then echo 'Asterisk extensions.conf not found'; exit 1; fi
if sudo grep -Eq '^\[zvonko-inbound\][[:space:]]*$' "$DIALPLAN"; then
 echo 'zvonko-inbound already exists. Will not overwrite it.'
 sudo asterisk -rx 'dialplan show zvonko-inbound'
 exit 0
fi
echo 'Checking Asterisk echo application...'
sudo asterisk -rx 'module show like app_echo'
sudo cp -p "$DIALPLAN" "$DIALPLAN.before-zvonko-test"
cat <<'DIALPLAN_EOF' | sudo tee -a "$DIALPLAN" >/dev/null

; Zvonko pilot ONLY: verify real audio flow through local Asterisk.
; No outbound dialplan; incoming Novofon calls on dedicated SIP robot 200.
[zvonko-inbound]
exten => s,1,NoOp(Zvonko first call audio path check)
 same => n,Answer()
 same => n,Wait(1)
 same => n,Playback(beep)
 same => n,Echo()
 same => n,Hangup()

; Novofon may pass internal extension or SIP login as Request-URI.
exten => _X.,1,Goto(s,1)
DIALPLAN_EOF
sudo asterisk -rx 'dialplan reload'
echo '=== New Zvonko dialplan ==='
sudo asterisk -rx 'dialplan show zvonko-inbound'
echo 'READY TO TEST: dial internal 200 manually from softphone 100.'
echo 'If it rings, listen for beep and test echo, then stop the call.'
echo 'This verifies the Asterisk audio path, NOT AI speech.'
