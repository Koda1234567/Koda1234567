"""Asterisk ARI phone gateway: bidirectional RTP, on-prem Russian speech AI.
Inbound calls + authenticated human-initiated test to an allowlisted own number.
No broadcast dialer, no automatic advertising calls, no cloud PII storage.
"""
from __future__ import annotations
import asyncio,contextlib,hmac,json,logging,secrets,struct,time
from collections import deque
from typing import Any
import aiohttp
from aiohttp import web
import numpy as np
from config import Config,allowed_test_call
from voice import SpeechPipeline,rtp_payload,ulaw_decode,ulaw_encode,stop_requested,quick_voice_reply
from sales import SalesState,sales_instruction,fast_sales_reply

log=logging.getLogger('zvonko.phone')

class AsteriskARI:
    def __init__(self,cfg:Config,client:aiohttp.ClientSession):
        self.cfg,self.client=cfg,client

    async def call(self,method:str,path:str,params:dict|None=None)->dict:
        url=self.cfg.ari_base.rstrip('/')+path
        async with self.client.request(method,url,params=params,
            auth=aiohttp.BasicAuth(self.cfg.ari_user,self.cfg.ari_password),
            timeout=aiohttp.ClientTimeout(total=15)) as r:
            data=await r.text()
            if r.status>=400:
                raise RuntimeError(f'ARI {r.status} {path}: {data[:200]}')
            return json.loads(data) if data else {}

    def websocket_url(self)->str:
        return self.cfg.ari_base.rstrip('/').replace('http://','ws://').replace('https://','wss://')+'/events'

class RTPListener(asyncio.DatagramProtocol):
    def __init__(self,session:'PhoneCall'):
        self.session=session
        self.transport:asyncio.DatagramTransport|None=None
        self.target:tuple[str,int]|None=None
        self.seq=secrets.randbits(16)
        self.ts=secrets.randbits(32)
        self.ssrc=secrets.randbits(32)

    def connection_made(self,transport:asyncio.BaseTransport):
        self.transport=transport

    def datagram_received(self,data:bytes,addr:tuple[str,int]):
        if self.target is None:self.target=addr
        payload=rtp_payload(data)
        if not payload:return
        if data[1]&0x7f!=0:return
        self.session.receive_audio(payload)

    def send_audio(self,payload:bytes):
        if not self.transport or not self.target:return
        header=struct.pack('!BBHII',0x80,0,self.seq,self.ts,self.ssrc)
        self.transport.sendto(header+payload,self.target)
        self.seq=(self.seq+1)&0xffff
        self.ts=(self.ts+len(payload))&0xffffffff

    def close(self):
        if self.transport:self.transport.close()

class PhoneCall:
    def __init__(self,manager:'PhoneServer',channel_id:str,mode:str):
        self.manager=manager;self.cfg=manager.cfg;self.ari=manager.ari;self.ai=manager.ai
        self.channel_id=channel_id;self.mode=mode
        self.bridge_id='zvonko-bridge-'+secrets.token_hex(8)
        self.external_id='zvonko-media-'+secrets.token_hex(8)
        self.listener=RTPListener(self)
        self.audio_transport:asyncio.DatagramTransport|None=None
        self.pre_roll:deque[np.ndarray]=deque(maxlen=16)
        self.frames:list[np.ndarray]=[]
        self.frame_bytes=bytearray()
        self.playing=False;self.interrupt=asyncio.Event()
        self.voice_frames=0;self.silent_frames=0
        self.turn_task:asyncio.Task|None=None
        self.play_task:asyncio.Task|None=None
        self.timeout_task:asyncio.Task|None=None
        self.history:list[dict[str,str]]=[]
        self.sales=SalesState()
        self.closed=False

    async def setup(self):
        loop=asyncio.get_running_loop()
        self.audio_transport,_=await loop.create_datagram_endpoint(
            lambda:self.listener,local_addr=(self.cfg.media_host,0))
        port=self.audio_transport.get_extra_info('sockname')[1]
        try:
            await self.ari.call('POST','/bridges',{'type':'mixing','bridgeId':self.bridge_id})
            await self.ari.call('POST','/bridges/'+self.bridge_id+'/addChannel',{'channel':self.channel_id})
            await self.ari.call('POST','/channels/externalMedia',{
                'app':self.cfg.ari_app,'appArgs':'media',
                'external_host':f'{self.cfg.media_host}:{port}',
                'format':'ulaw','encapsulation':'rtp','transport':'udp',
                'channelId':self.external_id,
            })
            await self.ari.call('POST','/bridges/'+self.bridge_id+'/addChannel',
                                {'channel':self.external_id})
            try:
                port_data=await self.ari.call('GET',f'/channels/{self.external_id}/variable',
                                             {'variable':'UNICASTRTP_LOCAL_PORT'})
                self.listener.target=(self.cfg.media_host,int(port_data['value']))
            except Exception:
                log.info('Waiting for Asterisk first RTP packet to learn endpoint')
            self.timeout_task=asyncio.create_task(self.max_duration())
            welcome=('Здравствуйте! Это тестовый звонок ИИ-менеджера Звонко. '
                     'Вы сами запросили проверку. Какой вопрос о товаре вам интересен?'
                     if self.mode=='manual-test' else
                     'Здравствуйте! Это Звонко, голосовой ИИ-консультант. '
                     'Подскажите, какая у вас задача?')
            self.play_task=asyncio.create_task(self.say(welcome))
            log.info('Connected live call %s, media port %s',self.channel_id,port)
        except Exception:
            await self.close(hangup=True)
            raise

    async def max_duration(self):
        await asyncio.sleep(self.cfg.max_call_seconds)
        await self.close(hangup=True)

    def receive_audio(self,ulaw:bytes):
        if self.closed:return
        self.frame_bytes.extend(ulaw)
        while len(self.frame_bytes)>=160:
            pcm=ulaw_decode(bytes(self.frame_bytes[:160]))
            del self.frame_bytes[:160]
            try:speaking=self.ai.speech_frame(pcm)
            except Exception:return
            self.pre_roll.append(pcm)
            if speaking:
                self.voice_frames+=1
                self.silent_frames=0
                if self.playing and self.voice_frames>=4:self.interrupt.set()
            elif self.frames:self.silent_frames+=1
            if not self.frames and self.voice_frames>=3:
                self.frames=list(self.pre_roll)
            elif self.frames:self.frames.append(pcm)
            if self.frames and ((self.silent_frames>=26 and len(self.frames)>=22)
                                or len(self.frames)>=900):
                if self.turn_task is None or self.turn_task.done():
                    samples=np.concatenate(self.frames)
                    self.turn_task=asyncio.create_task(self.handle_turn(samples))
                self.frames=[];self.voice_frames=0
                self.silent_frames=0;self.pre_roll.clear()
            if not speaking and not self.frames:self.voice_frames=0

    async def handle_turn(self,samples:np.ndarray):
        try:
            if self.play_task and not self.play_task.done():
                self.interrupt.set()
                await self.play_task
            stt_started=time.monotonic()
            heard=await self.ai.transcribe(samples)
            if not heard:
                log.info('No speech recognized (STT %.2fs)',time.monotonic()-stt_started)
                return
            log.info('Recognized caller utterance (length=%d, STT %.2fs)',
                     len(heard),time.monotonic()-stt_started)
            if stop_requested(heard):
                await self.say('Понял. Больше не беспокою. Всего доброго.')
                await self.close(hangup=True)
                return
            self.sales.observe(heard)
            self.history.append({'role':'user','content':heard})
            quick=quick_voice_reply(heard)
            if quick:
                log.info('Instant hearing/greeting response without LLM')
                self.history.append({'role':'assistant','content':quick})
                self.play_task=asyncio.create_task(self.say(quick))
                await self.play_task
                return
            sales_reply=fast_sales_reply(heard,self.sales,self.cfg.sales_offer)
            if sales_reply:
                log.info('Fast sales response: stage %s, turn %d',
                         self.sales.objection or 'qualification',self.sales.turn)
                self.history.append({'role':'assistant','content':sales_reply})
                self.play_task=asyncio.create_task(self.say(sales_reply))
                await self.play_task
                if self.sales.caller_declined:
                    await self.close(hangup=True)
                return
            instruction=sales_instruction(self.sales,self.cfg.sales_offer,self.cfg.sales_goal)
            llm_started=time.monotonic()
            llm_task=asyncio.create_task(self.ai.respond(self.history,extra_instruction=instruction))
            try:
                try:
                    reply=await asyncio.wait_for(asyncio.shield(llm_task),timeout=3.0)
                except asyncio.TimeoutError:
                    log.info('AI generation >3s; giving audible waiting cue')
                    if not self.closed:
                        await self.say('Одну секунду, я думаю.')
                    reply=await asyncio.wait_for(llm_task,timeout=35.0)
            finally:
                if not llm_task.done():
                    llm_task.cancel()
            log.info('AI reply ready in %.2fs (length=%d)',
                     time.monotonic()-llm_started,len(reply))
            if self.closed:return
            self.history.append({'role':'assistant','content':reply})
            self.play_task=asyncio.create_task(self.say(reply))
            await self.play_task
        except asyncio.CancelledError:raise
        except Exception:
            log.exception('Voice turn failed')
            if not self.closed:
                with contextlib.suppress(Exception):
                    await self.say('Извините, техническая ошибка. Попробуйте позвонить позже.')
                await self.close(hangup=True)

    async def say(self,text:str):
        if self.closed:return
        self.playing=True;self.interrupt.clear()
        tts_started=time.monotonic()
        audio_seconds=0.0
        first_chunk_latency=None
        try:
            async def playback(phrase:str):
                nonlocal audio_seconds,first_chunk_latency
                loop=asyncio.get_running_loop()
                next_frame_at=None
                async for pcm in self.ai.stream_synthesize(phrase):
                    if self.closed or self.interrupt.is_set():break
                    if first_chunk_latency is None:
                        first_chunk_latency=time.monotonic()-tts_started
                    audio_seconds+=len(pcm)/8000
                    ulaw=ulaw_encode(pcm)
                    next_frame_at=max(next_frame_at or loop.time(),loop.time())
                    for offset in range(0,len(ulaw),160):
                        if self.closed or self.interrupt.is_set():return
                        frame=ulaw[offset:offset+160]
                        if len(frame)<160:frame+=b'\xff'*(160-len(frame))
                        self.listener.send_audio(frame)
                        next_frame_at+=0.020
                        await asyncio.sleep(max(0,next_frame_at-loop.time()))
            try:
                await playback(text)
            except (KeyError,ValueError):
                log.warning('TTS rejected a word; giving safe fallback instead')
                if not self.closed and not self.interrupt.is_set():
                    await playback('Извините, повторите вопрос, пожалуйста.')
            log.info('Reply played: first audio %.2fs; total audio %.2fs',
                     first_chunk_latency or 0.,audio_seconds)
        finally:self.playing=False

    async def close(self,hangup:bool=False):
        if self.closed:return
        self.closed=True;self.interrupt.set()
        if self.timeout_task:self.timeout_task.cancel()
        self.listener.close()
        for task in (self.turn_task,self.play_task):
            if task and task is not asyncio.current_task() and not task.done():
                task.cancel()
        if self.ari:
            for path in ('/bridges/'+self.bridge_id,'/channels/'+self.external_id):
                with contextlib.suppress(Exception):await self.ari.call('DELETE',path)
            if hangup:
                with contextlib.suppress(Exception):
                    await self.ari.call('DELETE','/channels/'+self.channel_id)
        self.manager.calls.pop(self.channel_id,None)
        log.info('Closed call %s',self.channel_id)

class PhoneServer:
    def __init__(self,cfg:Config):
        self.cfg=cfg;self.http=None;self.ari=None;self.ai=None
        self.calls:dict[str,PhoneCall]={}
        self.call_class=PhoneCall # overridable by isolated v3, old route unchanged
        self.connected=False
        self.last_test_call=0.
        self.event_task=None

    async def start(self):
        self.http=aiohttp.ClientSession()
        self.ari=AsteriskARI(self.cfg,self.http)
        self.ai=SpeechPipeline(self.cfg,self.http)
        log.info('Loading Russian speech recognition and neural voices locally')
        await asyncio.to_thread(self.ai.load_models)
        self.event_task=asyncio.create_task(self.watch_ari())

    async def watch_ari(self):
        while True:
            try:
                async with self.http.ws_connect(
                    self.ari.websocket_url(),params={'app':self.cfg.ari_app},
                    auth=aiohttp.BasicAuth(self.cfg.ari_user,self.cfg.ari_password),
                    heartbeat=25,timeout=aiohttp.ClientTimeout(total=0)) as ws:
                    self.connected=True
                    log.info('Connected to local Asterisk ARI')
                    async for message in ws:
                        if message.type==aiohttp.WSMsgType.TEXT:
                            await self.handle_event(json.loads(message.data))
                        elif message.type in (aiohttp.WSMsgType.ERROR,aiohttp.WSMsgType.CLOSED):
                            break
            except asyncio.CancelledError:raise
            except Exception as exc:
                log.error('Asterisk ARI offline: %s',exc)
            finally:self.connected=False
            await asyncio.sleep(3)

    async def handle_event(self,event:dict[str,Any]):
        typ=event.get('type')
        ch=(event.get('channel') or {}).get('id','')
        if not ch:return
        if typ=='StasisStart':
            if ch.startswith('zvonko-media-') or ch in self.calls:return
            if len(self.calls)>=1:
                log.warning('Rejected extra call: max concurrency one')
                with contextlib.suppress(Exception):await self.ari.call('DELETE','/channels/'+ch)
                return
            args=event.get('args') or []
            mode=args[0] if args else 'inbound'
            if mode not in ('inbound','manual-test'):
                with contextlib.suppress(Exception):await self.ari.call('DELETE','/channels/'+ch)
                return
            call=self.call_class(self,ch,mode)
            self.calls[ch]=call
            if mode=='inbound':
                with contextlib.suppress(Exception):
                    await self.ari.call('POST','/channels/'+ch+'/answer')
            asyncio.create_task(call.setup())
        elif typ in ('StasisEnd','ChannelDestroyed') and ch in self.calls:
            asyncio.create_task(self.calls[ch].close())

    async def stop(self):
        if self.event_task:self.event_task.cancel()
        await asyncio.gather(*(c.close(hangup=True) for c in list(self.calls.values())),
                             return_exceptions=True)
        if self.http:await self.http.close()

    def authorized(self,request:web.Request)->bool:
        token=request.headers.get('Authorization','').removeprefix('Bearer ').strip()
        return hmac.compare_digest(token,self.cfg.admin_token)

    async def health(self,request:web.Request)->web.Response:
        return web.json_response({'asterisk':self.connected,'activeCalls':len(self.calls),
            'sipRegistration':'not_verified','bulkDialer':False,'outboundTest':self.cfg.enable_test_outbound})

    async def manual_test(self,request:web.Request)->web.Response:
        if not self.authorized(request):raise web.HTTPUnauthorized()
        if request.content_length is not None and request.content_length>2000:
            raise web.HTTPRequestEntityTooLarge(max_size=2000,actual_size=request.content_length)
        try:data=await request.json()
        except (ValueError,TypeError):raise web.HTTPBadRequest(text='Expected JSON')
        number=data.get('number') if isinstance(data,dict) else None
        if not isinstance(number,str) or not allowed_test_call(number,self.cfg):
            raise web.HTTPForbidden(text='Own +7 number not allowlisted')
        if not self.connected or not self.ari:
            raise web.HTTPServiceUnavailable(text='Asterisk not connected')
        if self.calls:raise web.HTTPConflict(text='Only one test call at a time')
        now=time.monotonic()
        if now-self.last_test_call<90:
            raise web.HTTPTooManyRequests(text='Wait at least 90 seconds')
        self.last_test_call=now
        try:
            result=await self.ari.call('POST','/channels',{
                'endpoint':f'PJSIP/{number}@{self.cfg.trunk_endpoint}',
                'app':self.cfg.ari_app,
                'appArgs':'manual-test',
                'callerId':self.cfg.caller_id,
                'timeout':25,
            })
        except Exception:
            log.exception('Operator refused test originate')
            raise web.HTTPBadGateway(text='SIP trunk rejected test originate')
        return web.json_response({'accepted':True,'channelId':result.get('id'),
               'note':'Asterisk accepted manual test. Delivery or answer not confirmed.'})

def create_app(server:PhoneServer)->web.Application:
    app=web.Application(client_max_size=2048)
    app.add_routes([web.get('/health',server.health),
                    web.post('/manual-test',server.manual_test)])
    return app

async def main():
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s')
    cfg=Config();cfg.validate()
    server=PhoneServer(cfg)
    await server.start()
    runner=web.AppRunner(create_app(server))
    await runner.setup()
    site=web.TCPSite(runner,host=cfg.admin_host,port=cfg.admin_port)
    await site.start()
    log.info('Phone control API: localhost %d only',cfg.admin_port)
    try:await asyncio.Event().wait()
    finally:
        await runner.cleanup()
        await server.stop()

if __name__=='__main__':
    asyncio.run(main())
