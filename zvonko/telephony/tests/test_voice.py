import os,sys
sys.path.insert(0,os.path.dirname(os.path.dirname(__file__)))
from dataclasses import replace
import numpy as np
from config import Config,allowed_test_call
from voice import ulaw_encode,ulaw_decode,rtp_payload,stop_requested,quick_voice_reply

def test_ulaw_roundtrip():
    x=np.array([-32000,-20000,-5000,-100,-1,0,1,100,5000,20000,32000],dtype=np.int16)
    r=ulaw_decode(ulaw_encode(x))
    assert r.shape==x.shape
    assert abs(int(r[0])-int(x[0]))<1200
    assert abs(int(r[5]))<30

def test_rtp():
    header=bytes([0x80,0,0,1,0,0,0,0,0,0,0,1])
    assert rtp_payload(header+b'hello')==b'hello'
    assert rtp_payload(b'bad') is None
    assert rtp_payload(bytes([0xa0,0])+header[2:]+b'hello'+bytes([1]))==b'hello'

def test_manual_allowlist():
    cfg=Config(ari_password='X',admin_token='Y'*32,enable_test_outbound=True,
        caller_id='+79990000000',test_numbers=frozenset({'+79991234567'}))
    assert allowed_test_call('+79991234567',cfg)
    for n in ['+79990000000','79991234567','+7999123456','+79991234567@bad']:
        assert not allowed_test_call(n,cfg)
    assert not allowed_test_call('+79991234567',replace(cfg,enable_test_outbound=False))

def test_stop():
    assert stop_requested('Больше не звоните пожалуйста')
    assert not stop_requested('Перезвоните завтра')

def test_quick_voice_reply_hello_and_hearing():
    assert 'слышу' in quick_voice_reply('Привет, слышно меня?')
    assert quick_voice_reply('Слышите меня?') is not None
    assert quick_voice_reply('Алло!') is not None
    assert quick_voice_reply('Привет') is not None
    assert quick_voice_reply('Сколько стоит робот для склада?') is None
    assert quick_voice_reply('Здравствуйте, расскажите мне о подборе и обслуживании уборочного оборудования') is None
