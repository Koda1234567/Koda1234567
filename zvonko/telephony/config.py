from __future__ import annotations
from dataclasses import dataclass,field
import os,re

def env(name, default=''):
    return os.environ.get(name,default)

@dataclass(frozen=True)
class Config:
    ari_base:str=field(default_factory=lambda:env('ARI_URL','http://127.0.0.1:8088/ari'))
    ari_user:str=field(default_factory=lambda:env('ARI_USER','zvonko'))
    ari_password:str=field(default_factory=lambda:env('ARI_PASSWORD'))
    ari_app:str='zvonko'
    media_host:str=field(default_factory=lambda:env('MEDIA_HOST','127.0.0.1'))
    admin_host:str=field(default_factory=lambda:env('ADMIN_HOST','127.0.0.1'))
    admin_port:int=field(default_factory=lambda:int(env('ADMIN_PORT','8766')))
    admin_token:str=field(default_factory=lambda:env('ADMIN_TOKEN'))
    trunk_endpoint:str=field(default_factory=lambda:env('SIP_TRUNK','mytrunk'))
    caller_id:str=field(default_factory=lambda:env('CALLER_ID'))
    test_numbers:frozenset[str]=field(default_factory=lambda:frozenset(x.strip() for x in env('TEST_NUMBERS').split(',') if x.strip()))
    enable_test_outbound:bool=field(default_factory=lambda:env('ENABLE_TEST_OUTBOUND')=='true')
    ollama_url:str=field(default_factory=lambda:env('OLLAMA_URL','http://127.0.0.1:11434'))
    ollama_model:str=field(default_factory=lambda:env('OLLAMA_MODEL','qwen2.5:7b'))
    whisper_model:str=field(default_factory=lambda:env('WHISPER_MODEL','small'))
    whisper_device:str=field(default_factory=lambda:env('WHISPER_DEVICE','cpu'))
    whisper_compute_type:str=field(default_factory=lambda:env('WHISPER_COMPUTE_TYPE','int8'))
    tts_engine:str=field(default_factory=lambda:env('TTS_ENGINE','piper').strip().lower())
    allow_cloud_tts:bool=field(default_factory=lambda:env('ALLOW_CLOUD_TTS','false').lower()=='true')
    elevenlabs_api_key:str=field(default_factory=lambda:env('ELEVENLABS_API_KEY'))
    elevenlabs_voice_id:str=field(default_factory=lambda:env('ELEVENLABS_VOICE_ID'))
    elevenlabs_model:str=field(default_factory=lambda:env('ELEVENLABS_MODEL','eleven_flash_v2_5'))
    piper_voice_path:str=field(default_factory=lambda:env('PIPER_VOICE_PATH',os.path.expanduser('~/.local/share/zvonko/voices/ru_RU-dmitri-medium.onnx')))
    piper_length_scale:float=field(default_factory=lambda:float(env('PIPER_LENGTH_SCALE','0.95')))
    silero_model_path:str=field(default_factory=lambda:env('SILERO_MODEL_PATH',os.path.expanduser('~/.local/share/zvonko/voices/v5_cis_base_nostress.jit')))
    silero_speaker:str=field(default_factory=lambda:env('SILERO_SPEAKER','ru_ekaterina'))
    sales_offer:str=field(default_factory=lambda:env('SALES_OFFER','профессиональные поломоечные машины VMD'))
    sales_goal:str=field(default_factory=lambda:env('SALES_GOAL','выяснить тип объекта, площадь, способ уборки и предложить подбор с живым специалистом'))
    tts_model:str=field(default_factory=lambda:env('TTS_MODEL','vosk-model-tts-ru-0.9-multi'))
    tts_speaker:int=field(default_factory=lambda:int(env('TTS_SPEAKER','2')))
    product_info:str=field(default_factory=lambda:env('PRODUCT_INFO','Подбор профессиональной уборочной техники по запросу.'))
    minimum_rms:float=field(default_factory=lambda:float(env('MINIMUM_RMS','180')))
    vad_aggressiveness:int=field(default_factory=lambda:int(env('VAD_AGGRESSIVENESS','2')))
    max_call_seconds:int=field(default_factory=lambda:int(env('MAX_CALL_SECONDS','240')))

    def validate(self):
        if not self.ari_password or len(self.admin_token)<24:
            raise ValueError('Set strong ARI_PASSWORD and ADMIN_TOKEN')
        if self.admin_host not in ('127.0.0.1','::1','localhost'):
            raise ValueError('Admin API must bind to loopback')
        if not re.fullmatch('[a-zA-Z0-9_-]+',self.trunk_endpoint):
            raise ValueError('Invalid SIP trunk')
        if self.tts_engine not in ('piper','vosk','silero','elevenlabs'):
            raise ValueError('TTS_ENGINE must be piper, vosk, silero or elevenlabs')
        if self.tts_engine=='elevenlabs':
            if not self.allow_cloud_tts:
                raise ValueError('Set ALLOW_CLOUD_TTS=true explicitly before sending text to an external voice API')
            if not self.elevenlabs_api_key or not re.fullmatch(r'[A-Za-z0-9]{16,64}',self.elevenlabs_voice_id):
                raise ValueError('Provide ELEVENLABS_API_KEY and a valid ELEVENLABS_VOICE_ID in private env')
        if self.tts_engine=='silero' and self.silero_speaker not in ('ru_ekaterina','ru_eduard','ru_kejilgan'):
            raise ValueError('Unsupported free Silero CIS voice')
        if not 0.75 <= self.piper_length_scale <= 1.25:
            raise ValueError('PIPER_LENGTH_SCALE must be between 0.75 and 1.25')
        if not 0<=self.vad_aggressiveness<=3:
            raise ValueError('Invalid VAD setting')
        if self.enable_test_outbound:
            if not self.caller_id or not self.test_numbers:
                raise ValueError('Need CALLER_ID and TEST_NUMBERS')
            if any(not re.fullmatch(r'\+7\d{10}',n) for n in self.test_numbers):
                raise ValueError('Every test phone must be +7XXXXXXXXXX')

def allowed_test_call(number:str,cfg:Config)->bool:
    return bool(cfg.enable_test_outbound and re.fullmatch(r'\+7\d{10}',number)
                and number in cfg.test_numbers)
