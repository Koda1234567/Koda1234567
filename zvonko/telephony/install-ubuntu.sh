#!/usr/bin/env bash
# Dedicated NEW Ubuntu 24.04 VPS in Russia. Does not make telephone calls.
set -Eeuo pipefail
if [[ $EUID -ne 0 ]]; then echo 'Run with sudo' >&2; exit 1; fi
if [[ ! -f server.py || ! -f requirements.txt || ! -f .env.example ]]; then
 echo 'Run from the zvonko/telephony directory' >&2; exit 1
fi
source /etc/os-release
if [[ $ID != ubuntu || $VERSION_ID != 24.04 ]]; then
 echo 'Use Ubuntu 24.04' >&2; exit 1
fi
if [[ -f /etc/asterisk/pjsip.conf ]] && grep -Eq '^\[[^]]+\]' /etc/asterisk/pjsip.conf; then
 echo 'An existing Asterisk config is present. Refusing to overwrite it.' >&2; exit 1
fi
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends asterisk python3 python3-venv python3-pip git curl openssl ca-certificates ffmpeg libsndfile1 sox
id zvonko >/dev/null 2>&1 || useradd --system --home-dir /opt/zvonko --shell /usr/sbin/nologin zvonko
install -d -o zvonko -g zvonko -m 0750 /opt/zvonko
cp server.py voice.py config.py requirements.txt /opt/zvonko/
chown zvonko:zvonko /opt/zvonko/{server.py,voice.py,config.py,requirements.txt}
python3 -m venv /opt/zvonko/.venv
/opt/zvonko/.venv/bin/pip install --upgrade pip
/opt/zvonko/.venv/bin/pip install -r /opt/zvonko/requirements.txt
chown -R zvonko:zvonko /opt/zvonko/.venv
if [[ ! -f /etc/zvonko.env ]]; then
 install -m 0600 -o root -g root .env.example /etc/zvonko.env
fi
install -m 0644 -o root -g root zvonko.service /etc/systemd/system/zvonko.service
systemctl daemon-reload
systemctl disable --now zvonko.service >/dev/null 2>&1 || true
echo 'Asterisk and Zvonko runtime installed. No SIP config or calls were started.'
echo 'Next, create a separate SIP login for the robot and run configure-novofon.sh.'
