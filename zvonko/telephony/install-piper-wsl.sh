#!/usr/bin/env bash
# Upgrade Zvonko's local voice without changing SIP/Asterisk or buying telephony.
# Voice: Piper ru_RU-dmitri-medium, from the official rhasspy/piper-voices model.
set -Eeuo pipefail
umask 077
cd "$(dirname "$0")"
if [[ ! -x .venv/bin/python ]]; then
  echo 'Missing Python environment. Install speech AI first.' >&2
  exit 1
fi
ENV_FILE="$HOME/.config/zvonko/ai.env"
if [[ ! -f "$ENV_FILE" ]]; then
  echo 'Missing private AI configuration. Run enable-local-ai-wsl.sh first.' >&2
  exit 1
fi
MODEL_DIR="$HOME/.local/share/zvonko/voices"
MODEL="$MODEL_DIR/ru_RU-dmitri-medium.onnx"
URL_ROOT='https://huggingface.co/rhasspy/piper-voices/resolve/main/ru/ru_RU/dmitri/medium'
mkdir -p "$MODEL_DIR"
.venv/bin/python -m pip install 'piper-tts>=1.8,<1.9'
CURL_PROXY=()
if [[ -n "${PIPER_DOWNLOAD_PROXY:-}" ]]; then
  CURL_PROXY=(--proxy "$PIPER_DOWNLOAD_PROXY")
  echo 'Using requested HTTPS download proxy.'
fi
download_file() {
  local url="$1" target="$2" tmp
  if [[ -s "$target" ]]; then return 0; fi
  tmp="$(mktemp "$MODEL_DIR/.voice.XXXXXXXX")"
  if ! curl --fail --location --retry 3 --retry-delay 2 --connect-timeout 20 \
            --show-error "${CURL_PROXY[@]}" "$url" --output "$tmp"; then
    rm -f "$tmp"
    echo 'Voice download failed. If XRay is running, retry:' >&2
    echo 'PIPER_DOWNLOAD_PROXY=http://127.0.0.1:10801 bash install-piper-wsl.sh' >&2
    exit 1
  fi
  mv "$tmp" "$target"
}
echo 'Downloading official Russian Piper voice (about 63 MB)...'
download_file "$URL_ROOT/ru_RU-dmitri-medium.onnx" "$MODEL"
download_file "$URL_ROOT/ru_RU-dmitri-medium.onnx.json" "$MODEL.json"
download_file "$URL_ROOT/MODEL_CARD" "$MODEL_DIR/ru_RU-dmitri-MODEL_CARD"
.venv/bin/python - "$MODEL" <<'PY'
import sys,time,wave,tempfile
from pathlib import Path
from piper import PiperVoice,SynthesisConfig
model=Path(sys.argv[1])
assert model.stat().st_size > 20_000_000, 'Voice file appears incomplete'
voice=PiperVoice.load(model,use_cuda=False)
t=time.monotonic()
with tempfile.TemporaryDirectory() as d:
    path=Path(d)/'test.wav'
    with wave.open(str(path),'wb') as out:
        voice.synthesize_wav('Здравствуйте! Я Звонко. Какую задачу вы хотите решить?',
                             out,syn_config=SynthesisConfig(length_scale=0.95))
    with wave.open(str(path),'rb') as f:
        assert f.getnframes()>8000 and f.getnchannels()==1
        duration=f.getnframes()/f.getframerate()
        assert duration>1, 'No voice audio created'
print(f'Piper voice passed smoke test: {duration:.1f}s of speech in {time.monotonic()-t:.2f}s.')
PY
export ENV_FILE MODEL
python3 - <<'PY'
from pathlib import Path
import os,shlex
p=Path(os.environ['ENV_FILE'])
lines=p.read_text().splitlines()
updates={
 'TTS_ENGINE':'piper',
 'PIPER_VOICE_PATH':os.environ['MODEL'],
 'PIPER_LENGTH_SCALE':'0.95',
 'SALES_OFFER':'профессиональные поломоечные машины VMD',
 'SALES_GOAL':'выяснить задачу покупателя и предложить консультацию живого специалиста',
}
out=[line for line in lines if not any(line.startswith('export '+name+'=') for name in updates)]
out.extend('export '+key+'='+shlex.quote(value) for key,value in updates.items())
p.write_text('\n'.join(out)+'\n')
p.chmod(0o600)
print('Voice engine and B2B sales profile enabled in private local configuration.')
PY
echo 'READY. The existing SIP dialplan was not modified.'
echo 'In your running Zvonko terminal: Ctrl+C, git pull, bash start-local-ai-wsl.sh'
echo 'NOTE: Piper runtime is GPL-3.0-or-later. Review engine and voice licensing before commercial distribution.'
