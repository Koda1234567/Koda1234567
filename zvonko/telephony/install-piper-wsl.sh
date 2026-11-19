#!/usr/bin/env bash
# Upgrade local Zvonko to Piper neural Russian TTS without altering Asterisk or SIP.
set -Eeuo pipefail
umask 077
cd "$(dirname "$0")"
ENV_FILE="$HOME/.config/zvonko/ai.env"
VOICE_DIR="$HOME/.local/share/zvonko/voices"
VOICE_ID="ru_RU-dmitri-medium"
MODEL="$VOICE_DIR/$VOICE_ID.onnx"
if [[ ! -x .venv/bin/python || ! -f "$ENV_FILE" ]]; then
  echo 'Complete the existing local AI setup first (Python venv + ~/.config/zvonko/ai.env).' >&2
  exit 1
fi
mkdir -p "$VOICE_DIR"
# Optional XRay Windows proxy, used only for downloading.
if [[ -n "${ZVONKO_DOWNLOAD_PROXY:-${PIPER_DOWNLOAD_PROXY:-}}" ]]; then
  export HTTPS_PROXY="${ZVONKO_DOWNLOAD_PROXY:-${PIPER_DOWNLOAD_PROXY:-}}"
  export HTTP_PROXY="$HTTPS_PROXY"
  export NO_PROXY="localhost,127.0.0.1,::1"
  export no_proxy="$NO_PROXY"
  echo 'Using local proxy to download the new voice.'
fi
echo '=== Install fast local neural speech engine ==='
.venv/bin/python -m pip install 'piper-tts>=1.8,<1.9'
if [[ ! -s "$MODEL" || ! -s "$MODEL.json" ]]; then
  echo "=== Download Russian voice $VOICE_ID (~63MB) ==="
  .venv/bin/python -m piper.download_voices --download-dir "$VOICE_DIR" "$VOICE_ID"
fi
echo '=== Smoke-test the voice before switching the live call ==='
PIPER_VOICE_PATH="$MODEL" .venv/bin/python - <<'PY'
import os,sys,io,wave,time
from pathlib import Path
from piper import PiperVoice,SynthesisConfig
path=Path(os.environ['PIPER_VOICE_PATH'])
assert path.is_file() and path.stat().st_size>20_000_000, 'Voice model incomplete'
assert Path(str(path)+'.json').is_file(), 'Voice model config missing'
start=time.monotonic()
voice=PiperVoice.load(path,use_cuda=False)
with io.BytesIO() as output:
    with wave.open(output,'wb') as wav:
        voice.synthesize_wav('Здравствуйте. Я Звонко. Какую задачу вы хотите решить?',
                             wav,syn_config=SynthesisConfig(length_scale=0.95))
    output.seek(0)
    with wave.open(output,'rb') as wav:
        duration=wav.getnframes()/wav.getframerate()
        assert duration>1 and wav.getnchannels()==1
print(f'PIPER READY: {duration:.2f}s audio; initialization + synthesis {time.monotonic()-start:.2f}s')
PY
# Never echo or overwrite the existing ARI and admin secrets.
python3 - "$ENV_FILE" "$MODEL" <<'PY'
from pathlib import Path
import sys,shlex
env_path=Path(sys.argv[1])
settings={
  'TTS_ENGINE':'piper',
  'PIPER_VOICE_PATH':sys.argv[2],
  'PIPER_LENGTH_SCALE':'0.95',
  'SALES_OFFER':'профессиональные поломоечные машины VMD',
  'SALES_GOAL':'выяснить задачу клиента и предложить консультацию живого специалиста',
}
existing=env_path.read_text().splitlines()
remaining=[line for line in existing
           if not any(line.startswith('export '+name+'=') for name in settings)]
remaining.extend('export '+name+'='+shlex.quote(value) for name,value in settings.items())
env_path.write_text('\n'.join(remaining)+'\n')
env_path.chmod(0o600)
print('Piper + configurable sales profile enabled locally (secrets hidden).')
PY
echo 'READY: restart only Zvonko (Ctrl+C, then bash start-local-ai-wsl.sh).'
echo 'Piper engine is GPL-3.0; verify voice/base-model commercial rights before shipping a paid product.'
