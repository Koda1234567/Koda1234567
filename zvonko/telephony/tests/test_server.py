import os,sys,asyncio
sys.path.insert(0,os.path.dirname(os.path.dirname(__file__)))
from aiohttp.test_utils import TestClient,TestServer
from config import Config
from server import RTPListener,PhoneServer,create_app

class Stub:
    def __init__(self):self.data=[]
    def receive_audio(self,data):self.data.append(data)

def test_rtp_sender():
    p=Stub()
    listener=RTPListener(p)
    class Transport:
        def __init__(self):self.packets=[]
        def sendto(self,p,addr):self.packets.append((p,addr))
    t=Transport();listener.connection_made(t)
    listener.target=('127.0.0.1',4567)
    listener.send_audio(b'\xff'*160)
    packet,addr=t.packets[0]
    assert addr[1]==4567 and len(packet)==172 and packet[1]==0
    listener.datagram_received(packet,addr)
    assert p.data==[b'\xff'*160]

def test_manual_call_safety():
    async def go():
        cfg=Config(ari_password='A',admin_token='X'*32,enable_test_outbound=True,
            caller_id='+79990000000',test_numbers=frozenset({'+79991234567'}))
        app=create_app(PhoneServer(cfg))
        async with TestClient(TestServer(app)) as cl:
            r=await cl.post('/manual-test',json={'number':'+79991234567'})
            assert r.status==401
            h={'Authorization':'Bearer '+cfg.admin_token}
            r=await cl.post('/manual-test',json={'number':'+79990000001'},headers=h)
            assert r.status==403
            r=await cl.post('/manual-test',json={'number':'+79991234567'},headers=h)
            assert r.status==503
    asyncio.run(go())
