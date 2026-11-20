"""Telephone speech bridge: PCMU/G.711 codec, Russian STT, natural neural TTS.
Runs on a server in Russia. No browser synthetic voice or recorded audio.
"""
from __future__ import annotations
import asyncio
import wave
import re
import threading
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any
import aiohttp
import numpy as np
from scipy.signal import resample_poly

def ulaw_decode(data:bytes)->np.ndarray:
    u=np.frombuffer(data,dtype=np.uint8)
    x=np.bitwise_not(u)
    mantissa=(x&0x0F).astype(np.int32)
    exponent=((x>>4)&0x07).astype(np.int32)
    magnitude=((mantissa<<3)+0x84)<<exponent
    magnitude-=0x84
    return np.where((x&0x80)!=0,-magnitude,magnitude).astype(np.int16)

def ulaw_encode(pcm:np.ndarray)->bytes:
    x=pcm.astype(np.int32).copy()
    negative=x<0
    x=np.abs(x).clip(max=32635)+0x84
    exponent=np.floor(np.log2(x.astype(np.float64))).astype(np.int32)-7
    exponent=np.clip(exponent,0,7)
    mantissa=(x>>(exponent+3))&0x0F
    code=(~((exponent<<4)|mantissa))&0xFF
    code=np.where(negative,code&0x7F,code|0x80)
    return np.asarray(code,dtype=np.uint8).tobytes()

def rtp_payload(data:bytes)->bytes|None:
    if len(data)<12 or (data[0]>>6)!=2:return None
    cc=data[0]&0x0F
    pos=12+4*cc
    if len(data)<pos:return None
    if data[0]&0x10:
        if len(data)<pos+4:return None
        ext_words=int.from_bytes(data[pos+2:pos+4],'big')
        pos+=4+ext_words*4
        if len(data)<pos:return None
    end=len(data)
    if data[0]&0x20:
        pad=data[-1]
        if pad==0 or pad>end-pos:return None
        end-=pad
    return data[pos:end] if pos<=end else None

def rms(pcm:np.ndarray)->float:
    if not pcm.size:return 0
    return float(np.sqrt(np.mean(pcm.astype(np.float32)**2)))

# Vosk's Russian text front-end can raise KeyError on ASCII digits
# (observed KeyError: '4' during a live call). Speak numbers instead.
_UNITS=('ноль','один','два','три','четыре','пять','шесть','семь','восемь','девять')
_TEENS=('десять','одиннадцать','двенадцать','тринадцать','четырнадцать',
        'пятнадцать','шестнадцать','семнадцать','восемнадцать','девятнадцать')
_TENS=('','','двадцать','тридцать','сорок','пятьдесят','шестьдесят',
       'семьдесят','восемьдесят','девяносто')
_HUNDREDS=('','сто','двести','триста','четыреста','пятьсот','шестьсот',
           'семьсот','восемьсот','девятьсот')

def _below_thousand(n:int,feminine:bool=False)->str:
    parts=[]
    if n>=100:
        parts.append(_HUNDREDS[n//100])
        n%=100
    if 10<=n<=19:
        parts.append(_TEENS[n-10])
    else:
        if n>=20:
            parts.append(_TENS[n//10])
        unit=n%10
        if unit:
            parts.append(('одна' if feminine else 'один') if unit==1 else
                         ('две' if feminine else 'два') if unit==2 else _UNITS[unit])
    return ' '.join(parts)

def _spoken_number(value:str)->str:
    # Phone numbers and long IDs should be spelled digit by digit.
    if (len(value)>6 or (len(value)>1 and value.startswith('0'))):
        return ' '.join(_UNITS[int(d)] for d in value)
    n=int(value)
    if n==0:return _UNITS[0]
    if n<1000:return _below_thousand(n)
    thousands,rest=divmod(n,1000)
    ending=('тысяч' if 11<=thousands%100<=14 or thousands%10 not in (1,2,3,4)
            else 'тысяча' if thousands%10==1 else 'тысячи')
    prefix=_below_thousand(thousands,feminine=True)+' '+ending
    return (prefix+' '+_below_thousand(rest)) if rest else prefix

def normalize_tts_text(text:str)->str:
    """Convert model output to a safe, speakable Russian sentence for Vosk TTS."""
    text=re.sub(r'https?://\S+',' ',text)
    text=text.replace('₽',' рублей ').replace('№',' номер ').replace('%',' процентов ')
    text=re.sub(r'\d+',lambda m:_spoken_number(m.group()),text)
    # Drop markdown, emoji, math symbols that the Russian phoneme map may not know.
    text=re.sub(r'[^а-яёА-ЯЁa-zA-Z\s.,!?;:()\-—]', ' ',text)
    text=re.sub(r'\s+',' ',text).strip()
    text=re.sub(r'\s+([,.!?;:])',r'\1',text)
    return text or 'Повторите, пожалуйста.'

def concise_voice_reply(text:str,limit:int=105)->str:
    """Keep natural phone replies short so the caller is not waiting 13 seconds."""
    text=re.sub(r'\s+',' ',text).strip()
    if len(text)<=limit:return text
    sentences=re.split(r'(?<=[.!?])\s+',text)
    result=''
    for sentence in sentences:
        candidate=(result+' '+sentence).strip()
        if len(candidate)>limit:break
        result=candidate
    if result:return result
    shortened=text[:limit].rsplit(' ',1)[0].rstrip(' ,;:-')
    return shortened+'.' if shortened else text[:limit].rstrip()+'.'

class SpeechPipeline:
    def __init__(self,cfg:Any,http:aiohttp.ClientSession):
        self.cfg=cfg;self.http=http
        self._whisper=None;self._vad=None;self._tts=None
        self._piper=None;self._piper_config=None
        self._silero=None
        self._piper_lock=threading.Lock()

    def load_models(self):
        from faster_whisper import WhisperModel
        import webrtcvad
        self._whisper=WhisperModel(self.cfg.whisper_model,device=self.cfg.whisper_device,
                                   compute_type=self.cfg.whisper_compute_type)
        self._vad=webrtcvad.Vad(self.cfg.vad_aggressiveness)
        if self.cfg.tts_engine=='piper':
            from piper import PiperVoice,SynthesisConfig
            voice_path=Path(self.cfg.piper_voice_path).expanduser()
            if not voice_path.is_file() or not Path(str(voice_path)+'.json').is_file():
                raise RuntimeError('Piper Russian voice missing. Run install-piper-wsl.sh first.')
            self._piper=PiperVoice.load(voice_path,use_cuda=False)
            self._piper_config=SynthesisConfig(length_scale=self.cfg.piper_length_scale)
        elif self.cfg.tts_engine=='silero':
            from silero_voice import load_silero_model
            self._silero=load_silero_model(self.cfg.silero_model_path)
        elif self.cfg.tts_engine=='vosk':
            from vosk_tts import Model,Synth
            self._tts=Synth(Model(model_name=self.cfg.tts_model))
        elif self.cfg.tts_engine=='elevenlabs':
            # Cloud TTS is explicitly gated by Config.validate(); no local voice loaded.
            pass
        else:
            raise RuntimeError('Unknown speech engine')

    def speech_frame(self,pcm:np.ndarray)->bool:
        if self._vad is None:raise RuntimeError('Load speech models before calls')
        if len(pcm)!=160 or rms(pcm)<self.cfg.minimum_rms:return False
        return self._vad.is_speech(pcm.astype('<i2').tobytes(),8000)

    async def transcribe(self,pcm_8000:np.ndarray)->str:
        if self._whisper is None:raise RuntimeError('Whisper not loaded')
        def run():
            audio=resample_poly(pcm_8000.astype(np.float32)/32768.,2,1)
            parts,_=self._whisper.transcribe(
                audio,language='ru',beam_size=3,vad_filter=False,
                condition_on_previous_text=False,
                initial_prompt='Разговор по телефону, русский язык.')
            return ' '.join(x.text.strip() for x in parts).strip()
        return await asyncio.to_thread(run)

    async def respond(self,history:list[dict[str,str]],extra_instruction:str='')->str:
        system=('Ты русскоязычный ИИ-консультант, разговариваешь с человеком ПО ТЕЛЕФОНУ. '
          'Представься ИИ в самом начале. Общайся тепло и естественно: короткие '
          'фразы и один вопрос за раз, никаких длинных списков. '
          'Отвечай не более чем двумя короткими предложениями, примерно до двадцати слов. '
          'Разговор по входящему запросу либо ручному тесту на личный номер. '
          'Не придумывай цены или гарантии. Не собирай чувствительные данные. '
          'При отказе не уговаривай, попрощайся. '
          'Предлагай консультацию живого менеджера, но не обещай выполненных действий. '
          'Вот проверенные сведения о продукте: '+self.cfg.product_info[:1400]+
          (' '+extra_instruction[:1500] if extra_instruction else ''))
        payload={'model':self.cfg.ollama_model,
                 'messages':[{'role':'system','content':system}]+history[-12:],
                 'stream':False,'options':{'temperature':0.55,'num_predict':64,'num_ctx':2048}}
        async with self.http.post(self.cfg.ollama_url.rstrip('/')+'/api/chat',
                json=payload,timeout=aiohttp.ClientTimeout(total=45)) as r:
            r.raise_for_status()
            data=await r.json()
        reply=data.get('message',{}).get('content','').strip()
        if not reply:raise RuntimeError('LLM returned empty response')
        return concise_voice_reply(reply)

    async def synthesize(self,text:str)->np.ndarray:
        if self._piper is not None or self.cfg.tts_engine in ('elevenlabs','silero'):
            chunks=[part async for part in self.stream_synthesize(text)]
            return np.concatenate(chunks) if chunks else np.empty(0,dtype=np.int16)
        if self._tts is None:raise RuntimeError('Vosk TTS not loaded')
        def run():
            with NamedTemporaryFile(suffix='.wav',delete=False) as f:path=f.name
            try:
                self._tts.synth(normalize_tts_text(text),path,speaker_id=self.cfg.tts_speaker)
                with wave.open(path,'rb') as wav:
                    rate=wav.getframerate()
                    if wav.getnchannels()!=1 or wav.getsampwidth()!=2:
                        raise RuntimeError('Expected mono PCM16 WAV')
                    samples=np.frombuffer(wav.readframes(wav.getnframes()),dtype='<i2')
                from math import gcd
                g=gcd(rate,8000)
                return np.clip(resample_poly(samples.astype(np.float32),
                        8000//g,rate//g),-32768,32767).astype(np.int16)
            finally:Path(path).unlink(missing_ok=True)
        return await asyncio.to_thread(run)

    async def _stream_elevenlabs(self,text:str):
        """Explicit opt-in cloud voice: stream raw PCM16 at 16kHz to 8kHz RTP.

        Only the AI-generated text is sent; caller audio/recordings stay local.
        The user must supply a valid key privately and authorize cloud TTS.
        """
        if not self.cfg.allow_cloud_tts:
            raise RuntimeError('Cloud TTS requires explicit permission')
        import re as _re
        if not _re.fullmatch(r'[A-Za-z0-9]{16,64}',self.cfg.elevenlabs_voice_id):
            raise ValueError('Invalid voice ID')
        url=('https://api.elevenlabs.io/v1/text-to-speech/'
             +self.cfg.elevenlabs_voice_id+'/stream')
        query={'output_format':'pcm_16000'}
        payload={'text':normalize_tts_text(text),
                 'model_id':self.cfg.elevenlabs_model,
                 'language_code':'ru'}
        headers={'xi-api-key':self.cfg.elevenlabs_api_key,
                 'Content-Type':'application/json'}
        timeout=aiohttp.ClientTimeout(total=25,connect=6,sock_read=15)
        async with self.http.post(url,headers=headers,params=query,
                                  json=payload,timeout=timeout) as response:
            if response.status!=200:
                # Do not log any response text: it may include account metadata.
                raise RuntimeError(f'Cloud voice HTTP {response.status}')
            leftover=bytearray()
            async for data in response.content.iter_chunked(3200):
                leftover.extend(data)
                while len(leftover)>=3200:
                    pcm=np.frombuffer(bytes(leftover[:3200]),dtype='<i2')
                    del leftover[:3200]
                    yield np.clip(resample_poly(pcm.astype(np.float32),1,2),
                                  -32768,32767).astype(np.int16)
            if len(leftover)>=2:
                pcm=np.frombuffer(bytes(leftover[:len(leftover)//2*2]),dtype='<i2')
                yield np.clip(resample_poly(pcm.astype(np.float32),1,2),
                              -32768,32767).astype(np.int16)

    async def stream_synthesize(self,text:str):
        """Yield PCM16 at 8kHz as a Piper voice generates each speech chunk.

        Piper runs on CPU while Ollama uses the GPU. No waveform needs to be
        fully generated before the first audio packet reaches the SIP caller.
        """
        if self.cfg.tts_engine=='elevenlabs':
            async for pcm in self._stream_elevenlabs(text):
                yield pcm
            return
        if self.cfg.tts_engine=='silero':
            if self._silero is None:
                raise RuntimeError('Silero voice was not loaded')
            from silero_voice import synthesize_silero_8k
            pcm = await asyncio.to_thread(
                synthesize_silero_8k, self._silero, text, self.cfg.silero_speaker)
            if len(pcm):
                yield pcm
            return
        if self._piper is None:
            yield await self.synthesize(text)
            return
        loop=asyncio.get_running_loop()
        queue=asyncio.Queue()
        done=object()

        def produce():
            from math import gcd
            try:
                with self._piper_lock:
                    for chunk in self._piper.synthesize(
                            normalize_tts_text(text),syn_config=self._piper_config):
                        if chunk.sample_channels != 1 or chunk.sample_width != 2:
                            raise RuntimeError('Piper must output mono PCM16')
                        pcm=chunk.audio_int16_array
                        g=gcd(chunk.sample_rate,8000)
                        samples=np.clip(resample_poly(pcm.astype(np.float32),
                                      8000//g,chunk.sample_rate//g),
                                      -32768,32767).astype(np.int16)
                        loop.call_soon_threadsafe(queue.put_nowait,samples)
            except Exception as exc:
                loop.call_soon_threadsafe(queue.put_nowait,exc)
            finally:
                loop.call_soon_threadsafe(queue.put_nowait,done)

        worker=asyncio.create_task(asyncio.to_thread(produce))
        try:
            while True:
                part=await queue.get()
                if part is done:break
                if isinstance(part,Exception):raise part
                if len(part):yield part
        finally:
            if not worker.done():
                # Inference in a worker thread will finish in the background;
                # avoid blocking the call teardown.
                worker.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)
            else:
                await worker

def stop_requested(text:str)->bool:
    s=text.casefold()
    return any(x in s for x in (
        'не звоните','больше не звон','не беспокойте',
        'не надо звон','удалите мой номер','до свидания',
        'прощайте','отказываюсь'))


def quick_voice_reply(heard:str)->str|None:
    """Offline responses to simple audio checks, without waiting for the LLM.

    Use only for explicit short greetings/audio checks. Longer messages go to AI.
    Avoid logging or storing the caller's actual words.
    """
    words=set(re.findall(r'[а-яёa-z]+',heard.casefold()))
    if len(words)>9:return None
    if words & {'слышно','слышите','алло'}:
        return 'Да, я вас слышу! Я Звонко, голосовой ИИ. Чем могу помочь?'
    if words and words <= {'привет','здравствуйте','добрый','день','вечер','утро'}:
        return 'Здравствуйте! Я на связи. Подскажите, какая у вас задача?'
    return None
