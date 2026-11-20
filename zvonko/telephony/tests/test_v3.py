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
    from types import SimpleNamespace
    from unittest.mock import patch

    ai = SimpleNamespace(speech_frame=lambda pcm: (_ for _ in ()).throw(
        AssertionError('VAD must stay muted during playback')))
    manager = SimpleNamespace(cfg=Config(), ari=None, ai=ai)
    call = V3PhoneCall(manager, 'local-test', 'inbound')
    assert call._capture_ready is False
    call.receive_audio(b'\xff' * 320)
    assert not call.frames and not call.frame_bytes and call.epoch == 0

    async def pretend_tts(self, text):
        self.playing = True
        try:
            self.receive_audio(b'\xff' * 320)
            assert not self.frames and self.epoch == 0
        finally:
            self.playing = False

    with patch.object(PhoneCall, 'say', pretend_tts):
        asyncio.run(call.say('Здравствуйте! Это Звонко.'))

    assert call._capture_ready is True
    assert call._capture_blocked_until > time.monotonic()
    call.receive_audio(b'\xff' * 320)
    assert not call.frames and call.epoch == 0


def test_v3_listens_after_echo_guard_expires():
    """Only genuine post-greeting audio can become a new recognized turn."""
    from types import SimpleNamespace
    ai = SimpleNamespace(speech_frame=lambda pcm: True)
    manager = SimpleNamespace(cfg=Config(), ari=None, ai=ai)
    call = V3PhoneCall(manager, 'local-test', 'inbound')
    call._capture_ready = True
    call._capture_blocked_until = 0.0
    call.receive_audio(b'\xff' * 480)
    assert call.epoch == 1
    assert call.frames
    assert not call.interrupt.is_set()


def test_v3_does_not_lose_reply_to_new_microphone_packets():
    """Regression: once STT starts, RTP fragments cannot cancel the answer."""
    import asyncio
    from types import SimpleNamespace

    async def test_case():
        count = 0
        def speech_frame(_):
            nonlocal count
            count += 1
            return count <= 30

        async def transcribe(_):
            await asyncio.sleep(0.04)
            return 'Что вы продаёте?'

        ai = SimpleNamespace(speech_frame=speech_frame,
                             transcribe=transcribe, http=None)
        cfg = Config(ari_password='test', admin_token='x'*32)
        manager = SimpleNamespace(cfg=cfg, ari=None, ai=ai)
        call = V3PhoneCall(manager, 'one-test', 'inbound')
        call._capture_ready = True
        spoken = []

        async def record_speech(text):
            spoken.append(text)
            await asyncio.sleep(0.04)

        call.say = record_speech
        # 30 speech frames (20ms) + 22 frames of silence closes the question.
        call.receive_audio(b'\xff' * (160 * 52))
        assert call._processing_turn is True
        epoch = call.epoch
        # Before STT returns, fake another entire utterance from microphone
        # echo. The old code would start a second turn and cancel the first.
        call.receive_audio(b'\xff' * (160 * 50))
        assert call.epoch == epoch
        await asyncio.wait_for(call.turn_task, timeout=1)
        assert len(spoken) == 1, spoken
        assert 'VMD' in spoken[0] or 'ви эм ди' in spoken[0].casefold()
        assert call._processing_turn is False
        assert call._capture_ready is True

    asyncio.run(test_case())


def test_v3_speaks_if_local_model_stays_silent():
    """A local model timeout must speak an audible retry, not wait forever."""
    import asyncio
    import numpy as np
    from types import SimpleNamespace
    from unittest.mock import patch

    async def transcribe(_):
        return 'У меня нестандартная задача'

    async def slow_response(*args, **kwargs):
        await asyncio.sleep(60)
        yield 'Поздний ответ'

    async def test_case():
        ai = SimpleNamespace(transcribe=transcribe, http=None)
        cfg = Config(ari_password='test', admin_token='x'*32)
        manager = SimpleNamespace(cfg=cfg, ari=None, ai=ai)
        call = V3PhoneCall(manager, 'slow-test', 'inbound')
        call.epoch = 1
        call._processing_turn = True
        spoken = []

        async def record_speech(text):
            spoken.append(text)

        call.say = record_speech
        with patch('server_v3.product_answer', return_value=None), \
             patch('server_v3.quick_voice_reply', return_value=None), \
             patch('server_v3.fast_sales_reply', return_value=None), \
             patch('server_v3.stream_sales_response', slow_response), \
             patch('server_v3.V3_FIRST_PHRASE_TIMEOUT', 0.03), \
             patch('server_v3.V3_EXTENDED_PHRASE_TIMEOUT', 0.03):
            await asyncio.wait_for(
                call.handle_turn(np.zeros(8000, dtype=np.int16), 1),
                timeout=1)
        assert len(spoken) == 2
        assert 'Одну секунду' in spoken[0]
        assert 'Могу помочь' in spoken[1]
        assert call._processing_turn is False

    asyncio.run(test_case())


def test_v3_slow_model_can_finish_after_audible_cue():
    """The first deadline must NOT kill a Qwen reply arriving shortly after."""
    import asyncio
    import numpy as np
    from types import SimpleNamespace
    from unittest.mock import patch

    async def transcribe(_):
        return 'Подберите решение для моего помещения'

    async def delayed_response(*args, **kwargs):
        await asyncio.sleep(0.065)
        yield 'Для вашего объекта подберём технику по площади.'
        yield 'Какое покрытие пола?'

    async def test_case():
        ai = SimpleNamespace(transcribe=transcribe, http=None)
        cfg = Config(ari_password='secret', admin_token='x'*32)
        call = V3PhoneCall(SimpleNamespace(cfg=cfg, ari=None, ai=ai),
                           'slower-test', 'inbound')
        call.epoch = 1
        call._processing_turn = True
        spoken = []

        async def record_speech(reply):
            spoken.append(reply)
            await asyncio.sleep(0.001)

        call.say = record_speech
        with patch('server_v3.product_answer', return_value=None), \
             patch('server_v3.quick_voice_reply', return_value=None), \
             patch('server_v3.fast_sales_reply', return_value=None), \
             patch('server_v3.stream_sales_response', delayed_response), \
             patch('server_v3.V3_FIRST_PHRASE_TIMEOUT', 0.015), \
             patch('server_v3.V3_EXTENDED_PHRASE_TIMEOUT', 0.25):
            await asyncio.wait_for(
                call.handle_turn(np.zeros(8000, dtype=np.int16), 1),
                timeout=1)
        assert 'Одну секунду' in spoken[0]
        assert 'Для вашего объекта' in spoken[1]
        assert 'покрытие пола' in spoken[2]
        assert call._processing_turn is False

    asyncio.run(test_case())


def test_fast_brain_stays_local_and_is_prewarmed_before_calls():
    from pathlib import Path
    script=(Path(__file__).resolve().parents[1] / 'start-v3-wsl.sh').read_text()
    assert 'ollama show qwen3.5:2b' in script
    assert 'V3 local AI:' in script
    assert "model':name" in script
    assert "'think':False" in script
    assert "'keep_alive':'30m'" in script
    assert 'before the first telephone question' in script
