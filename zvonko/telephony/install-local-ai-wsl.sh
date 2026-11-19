#!/usr/bin/env bash
# Install AI dependencies for local, consent-based telephone conversation.
# This script DOES NOT change the working MicroSIP -> Asterisk echo test.
set -Eeuo pipefail
cd "$(dirname "$0")"
if [[ ! -f requirements.txt || ! -f voice.py ]]; then
 echo 'Run from the zvonko/telephony project directory.' >&2
 exit 1
fi
echo '=== Stage 1: local Python runtime (Ubuntu 24.04 / WSL2) ==='
sudo apt-get update
sudo apt-get install -y --no-install-recommends python3-venv python3-pip curl ffmpeg libsndfile1 ca-certificates
if [[ ! -x .venv/bin/python ]]; then
 python3 -m venv .venv
fi
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
echo '=== Stage 2: Ollama on Linux ==='
if ! command -v ollama >/dev/null 2>&1; then
 echo 'Downloading the official Ollama Linux installer from ollama.com'
 TMP="$(mktemp)"
 trap 'rm -f "$TMP"' EXIT
 curl --fail --location --show-error --silent https://ollama.com/install.sh --output "$TMP"
 sh "$TMP"
 rm -f "$TMP"
 trap - EXIT
fi
sudo systemctl start ollama
echo 'Waiting for Ollama localhost API'
for attempt in $(seq 1 25); do
 if curl --fail --silent http://127.0.0.1:11434/api/tags >/dev/null; then break; fi
 sleep 1
done
curl --fail --silent http://127.0.0.1:11434/api/tags >/dev/null ||
  { echo 'Ollama is not yet listening on localhost:11434' >&2; exit 1; }
echo '=== Stage 3: light Russian language model for 16GB RAM ==='
ollama pull qwen2.5:1.5b
echo '=== Stage 4: download and load offline speech recognition ==='
.venv/bin/python - <<'PY'
from faster_whisper import WhisperModel
WhisperModel('tiny',device='cpu',compute_type='int8')
print('Whisper tiny: loaded')
PY
echo '=== Stage 5: local Russian TTS voice check ==='
.venv/bin/python - <<'PY'
from vosk_tts import Model,Synth
from pathlib import Path
import tempfile,wave
synth=Synth(Model(model_name='vosk-model-tts-ru-0.9-multi'))
with tempfile.TemporaryDirectory() as d:
 p=str(Path(d)/'test.wav')
 synth.synth('Здравствуйте, это локальный голос Звонко.',p,speaker_id=2)
 with wave.open(p,'rb') as f:
  print('Vosk neural Russian TTS:',f.getframerate(),'Hz,',f.getnframes(),'samples')
print('Local speech engines initialized.')
PY
echo '=== READY: installed models; existing echo SIP dialplan remains unchanged ==='
echo 'Next: configure local-only Asterisk ARI and switch extension 200 from Echo to Stasis.'
