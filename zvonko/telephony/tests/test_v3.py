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
