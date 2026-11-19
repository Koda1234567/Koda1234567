#!/usr/bin/env bash
# Read-only infrastructure checks; no secrets or telephone calls.
set -uo pipefail
echo '=== Zvonko first call: server checks ==='
if ! command -v asterisk >/dev/null; then echo 'Asterisk not installed'; exit 2; fi
if ! asterisk -rx 'core show uptime' >/dev/null 2>&1; then
 echo 'Asterisk not running'; exit 2
fi
echo 'Asterisk: RUNNING'
echo 'SIP registrations:'
asterisk -rx 'pjsip show registrations' 2>&1 | sed -E 's/([a-zA-Z0-9_.-]+):[^ @]+@/\1:***@/g' | head -30
echo 'ARI:'
asterisk -rx 'module show like res_ari' 2>&1 | head -15
echo 'Gateway process:'
systemctl is-active zvonko || true
echo 'Gateway local health:'
curl --max-time 3 -fsS http://127.0.0.1:8766/health 2>/dev/null || echo 'Gateway offline'
echo 'Ollama local API:'
if curl --max-time 3 -fsS http://127.0.0.1:11434/api/tags >/dev/null; then
 echo 'Ollama online'
else
 echo 'Ollama offline'
fi
echo 'These checks alone do not prove a successful SIP call or natural voice.'
