#!/usr/bin/env bash
# Local Zvonko v3 server: separate ARI app and health port from original 200.
set -Eeuo pipefail
cd "$(dirname "$0")"
ENV_FILE="$HOME/.config/zvonko/ai.env"
if [[ ! -f "$ENV_FILE" || ! -x .venv/bin/python ]]; then
  echo 'Local AI installation missing: complete the previous setup first.' >&2
  exit 1
fi
if ! curl --noproxy '*' --fail --silent --max-time 3 http://127.0.0.1:11434/api/tags >/dev/null; then
  echo 'Ollama offline: sudo systemctl start ollama' >&2
  exit 1
fi
set -a
source "$ENV_FILE"
set +a
# A small local brain is preferable for live telephone latency.
# Only select models that are actually installed; never download on startup.
if [[ -z "${OLLAMA_MODEL_V3:-}" ]]; then
  if ollama show qwen3.5:2b >/dev/null 2>&1; then
    OLLAMA_MODEL_V3=qwen3.5:2b
  else
    OLLAMA_MODEL_V3=qwen3.5:4b
  fi
fi
export OLLAMA_MODEL_V3
if ! ollama show "$OLLAMA_MODEL_V3" >/dev/null 2>&1; then
  echo "Local Ollama model $OLLAMA_MODEL_V3 missing. Install with: ollama pull $OLLAMA_MODEL_V3" >&2
  exit 1
fi
echo "V3 local AI: $OLLAMA_MODEL_V3 (offline Ollama, no paid APIs)"
# Use the free, local MIT Silero voice automatically once installed.
# Keep the existing Piper fallback until the Silero model passes its installer.
SILERO_MODEL_PATH="$HOME/.local/share/zvonko/voices/v5_cis_base_nostress.jit"
SILERO_READY="$HOME/.local/share/zvonko/voices/v5_cis_base_nostress.ready"
FREE_V3_ENGINE=piper
if [[ -s "$SILERO_MODEL_PATH" && -s "$SILERO_READY" ]]; then
  FREE_V3_ENGINE=silero
fi
export TTS_ENGINE="${ZVONKO_VOICE_BACKEND:-$FREE_V3_ENGINE}"
if [[ "$TTS_ENGINE" == silero ]]; then
  if [[ ! -s "$SILERO_MODEL_PATH" || ! -s "$SILERO_READY" ]]; then
    echo 'Silero NOT verified. Run: bash install-silero-v3-wsl.sh' >&2
    exit 1
  fi
  export SILERO_MODEL_PATH
  export SILERO_SPEAKER="${ZVONKO_SILERO_SPEAKER:-ru_ekaterina}"
  case "$SILERO_SPEAKER" in
    ru_ekaterina|ru_eduard|ru_kejilgan) ;;
    *) echo 'Invalid free Silero voice. Try ru_ekaterina, ru_eduard or ru_kejilgan.' >&2; exit 1 ;;
  esac
  echo "V3 free local Silero voice: $SILERO_SPEAKER (MIT license)"
fi
# Optional paid TTS remains disabled unless explicitly enabled with credentials.
if [[ "$TTS_ENGINE" == elevenlabs ]]; then
  if [[ "${ALLOW_CLOUD_TTS:-false}" != true ]]; then
    echo 'Cloud voice not authorized. Run bash configure-elevenlabs-wsl.sh' >&2; exit 1
  fi
  echo 'Cloud ElevenLabs voice enabled: AI reply TEXT leaves the computer.'
fi
# Private, independently selected voice for the v3 trial. Never modify the
# shared ai.env: extension 200 can keep its existing TTS configuration.
VOICE_FILE="$HOME/.config/zvonko/v3-voice"
V3_PIPER_VOICE="${ZVONKO_V3_PIPER_VOICE:-}"
if [[ -z "$V3_PIPER_VOICE" && -f "$VOICE_FILE" ]]; then
  IFS= read -r V3_PIPER_VOICE < "$VOICE_FILE" || true
fi
V3_PIPER_VOICE="${V3_PIPER_VOICE:-denis}"
case "$V3_PIPER_VOICE" in
  denis|dmitri|irina|ruslan) ;;
  *) echo 'Invalid v3 Piper voice. Allowed: denis, dmitri, irina, ruslan.' >&2; exit 1 ;;
esac
export PIPER_VOICE_PATH="$HOME/.local/share/zvonko/voices/ru_RU-$V3_PIPER_VOICE-medium.onnx"
if [[ "$TTS_ENGINE" == piper && ( ! -s "$PIPER_VOICE_PATH" || ! -s "$PIPER_VOICE_PATH.json" ) ]]; then
  echo "V3 Piper $V3_PIPER_VOICE not installed: bash select-v3-voice-wsl.sh $V3_PIPER_VOICE" >&2
  exit 1
fi
if [[ "$TTS_ENGINE" == piper ]]; then
  echo "V3 local voice: $V3_PIPER_VOICE (fallback; Silero not installed or not selected)"
fi
# Run an actual short local inference before accepting live SIP calls. Loading
# weights alone does not warm the first token path on all CUDA backends.
# Failure is explicit in the console but never blocks use of the older model.
echo 'Warming up local Ollama before the first telephone question...'
.venv/bin/python - <<'PY' || echo 'WARNING: Ollama warm-up failed; check ollama ps and console logs if first reply is slow.'
import json,os,time,urllib.error,urllib.request
name=os.environ['OLLAMA_MODEL_V3']
base=os.environ.get('OLLAMA_URL','http://127.0.0.1:11434').rstrip('/')
if not (base.startswith('http://127.0.0.1:') or base.startswith('http://localhost:')):
    raise SystemExit('Warm-up only supports local Ollama on loopback')
payload={
 'model':name,'messages':[{'role':'user','content':'Ответь одним словом: готово.'}],
 'stream':False,'think':False,'keep_alive':'30m',
 'options':{'num_predict':20,'num_ctx':2048,'temperature':0.0},
}
request=urllib.request.Request(base+'/api/chat',data=json.dumps(payload).encode('utf-8'),
                              headers={'Content-Type':'application/json'},method='POST')
started=time.monotonic()
try:
    with urllib.request.urlopen(request,timeout=90) as response:
        result=json.load(response)
    content=(result.get('message') or {}).get('content','')
    print(f'V3 brain warmed in {time.monotonic()-started:.1f}s; model={name}; reply_chars={len(content)}')
    if not content:
        print('WARNING: Ollama returned empty text. Try qwen3.5:2b or check model status.')
except (TimeoutError,urllib.error.URLError,ValueError) as exc:
    print(f'WARNING: Ollama warm-up failed after {time.monotonic()-started:.1f}s ({type(exc).__name__}).')
PY
echo 'Starting V3. Wait for Connected to local Asterisk ARI, then call 201 in MicroSIP.'
echo 'Original 200 can still run separately. Ctrl+C stops only V3.'
exec .venv/bin/python -u server_v3.py
