"""V3 low-latency speech chunking and isolated call routing smoke tests."""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from v3_engine import SpeechChunker
from server_v3 import V3PhoneCall, V3PhoneServer
from server import PhoneCall, PhoneServer
from config import Config


def test_chunks_first_sentence_before_completion():
    c = SpeechChunker()
    assert c.feed('Для склада подойдёт ') == []
    first = c.feed('подбор под площадь. ')
    assert first == ['Для склада подойдёт подбор под площадь.']
    assert not c.full
    second = c.feed('А какая площадь помещения?')
    assert second == ['А какая площадь помещения?']
    assert c.full
    assert c.flush() == []


def test_long_unpunctuated_reply_can_start_early():
    c = SpeechChunker()
    response = 'Понимаю вашу задачу и предлагаю сначала уточнить площадь и покрытие пола на объекте'
    first = c.feed(response)
    assert len(first) == 1
    assert len(first[0]) < len(response)
    assert ' ' in first[0]
    rest = c.flush()
    assert len(rest) == 1


def test_chunker_limits_speech():
    c = SpeechChunker(max_chunks=2, max_chars=70)
    c.feed('Это большая производственная площадь. ')
    c.feed('Мы поможем подобрать подходящее оборудование. ')
    assert c.full
    assert c.feed('Ещё одно длинное предложение.') == []
    assert c.total_chars <= 70


def test_server_supports_distinct_call_class_and_ari_app():
    cfg = Config(ari_password='password', admin_token='x' * 32,
                 ari_app='zvonko3', enable_test_outbound=False)
    legacy = PhoneServer(cfg)
    v3 = V3PhoneServer(cfg)
    assert legacy.call_class is PhoneCall
    assert v3.call_class is V3PhoneCall
    assert cfg.ari_app == 'zvonko3'


def test_v3_independent_routing_is_in_stasis_app():
    # Setup script must not replace extension 200 or the original app.
    from pathlib import Path
    script = Path(__file__).resolve().parents[1] / 'setup-v3-wsl.sh'
    text = script.read_text()
    assert 'Stasis(zvonko3,inbound)' in text
    assert 'exten => 201,1' in text
    assert '200 route not found' in text or 'Original 200 route not found' in text
    assert "systemctl restart asterisk" not in text


def test_live_agent_uses_latest_local_brain_without_paid_api():
    from pathlib import Path
    folder=Path(__file__).resolve().parents[1]
    for filename in ('setup-v3-wsl.sh','start-v3-wsl.sh','server_v3.py'):
        assert 'qwen3.5:4b' in (folder/filename).read_text()
    source=(folder/'v3_engine.py').read_text()
    assert "'think': False" in source
    assert "'stream': True" in source
    assert "'num_ctx': 4096" in source
    assert "'keep_alive': '30m'" in source


def test_v3_greeting_is_not_interrupted_by_microphone_echo():
    """Echo packets while the assistant speaks must not enter STT/VAD."""
    import asyncio
    import time
    from collections import deque
    from types import SimpleNamespace
    from unittest.mock import patch

    ai = SimpleNamespace(speech_frame=lambda pcm: (_ for _ in ()).throw(
        AssertionError('VAD must stay muted during playback')))
    manager = SimpleNamespace(cfg=Config(), ari=None, ai=ai)
    call = V3PhoneCall(manager, 'local-test', 'inbound')
    assert call._capture_ready is False
    call.receive_audio(b'\\xff' * 320)
    assert not call.frames and not call.frame_bytes and call.epoch == 0

    async def pretend_tts(self, text):
        self.playing = True
        try:
            self.receive_audio(b'\\xff' * 320)
            assert not self.frames and self.epoch == 0
        finally:
            self.playing = False

    with patch.object(PhoneCall, 'say', pretend_tts):
        asyncio.run(call.say('Здравствуйте! Это Звонко.'))

    assert call._capture_ready is True
    assert call._capture_blocked_until > time.monotonic()
    call.receive_audio(b'\\xff' * 320)
    assert not call.frames and call.epoch == 0


def test_v3_listens_after_echo_guard_expires():
    """Only genuine post-greeting audio can become a new recognized turn."""
    from types import SimpleNamespace
    ai = SimpleNamespace(speech_frame=lambda pcm: True)
    manager = SimpleNamespace(cfg=Config(), ari=None, ai=ai)
    call = V3PhoneCall(manager, 'local-test', 'inbound')
    call._capture_ready = True
    call._capture_blocked_until = 0.0
    call.receive_audio(b'\\xff' * 480)
    assert call.epoch == 1
    assert call.frames
    assert not call.interrupt.is_set()
