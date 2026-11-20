"""Free offline Silero voice regressions; no model download or torch dependency in CI."""
from __future__ import annotations
import contextlib
from dataclasses import replace
import os
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import Config
from silero_voice import normalize_silero_text, silero_token_ids, synthesize_silero_8k, SILERO_SAMPLE_RATE, SILERO_SPEAKER_IDS


class FakeAudio:
    def __init__(self, samples):
        self.samples = samples

    def detach(self):
        return self

    def cpu(self):
        return self

    def numpy(self):
        return self.samples


class FakeTensor:
    def __init__(self, values):
        self.values = values
        self.shape = (len(values),)

    def unsqueeze(self, axis):
        assert axis == 0
        self.shape = (1, len(self.values))
        return self


class FakeJitModel:
    # This mirrors the JIT object shown in Silero's official notebook.
    # Intentionally has NO apply_tts() attribute.
    def __call__(self, tokens, speaker_ids):
        from silero_voice import silero_token_ids
        assert tokens.shape == (1, len(tokens.values))
        assert tokens.values == silero_token_ids('Вопрос по VMD F60.')
        assert tokens.values[0] == 2 and tokens.values[-1] == 1
        assert speaker_ids.values == [28]  # Official ru_ekaterina speaker ID.
        return FakeAudio((np.sin(np.arange(48000, dtype=np.float32) / 17) * 0.4)[None, :])


def test_free_voice_uses_cyrillic_and_normalizes_models():
    assert 'ви эм ди' in normalize_silero_text('VMD F60 B52')
    assert 'эф' in normalize_silero_text('VMD F60 B52')
    assert not any(c.isascii() and c.isalpha()
                   for c in normalize_silero_text('VMD F60 B52'))


def test_jit_token_and_speaker_map_matches_official_notebook():
    assert SILERO_SAMPLE_RATE == 48000
    assert SILERO_SPEAKER_IDS['ru_ekaterina'] == 28
    assert SILERO_SPEAKER_IDS['ru_eduard'] == 27
    assert SILERO_SPEAKER_IDS['ru_kejilgan'] == 32
    codes = silero_token_ids('Привет!')
    assert codes[0] == 2 and codes[-1] == 1
    assert len(codes) > 5


def test_silero_uses_only_local_model_and_converts_to_rtp_pcm16():
    with patch.dict(sys.modules, {'torch': SimpleNamespace(
            inference_mode=contextlib.nullcontext,
            Tensor=type('Tensor', (), {}), LongTensor=FakeTensor)}):
        pcm = synthesize_silero_8k(
            FakeJitModel(), 'Вопрос по VMD F60.', 'ru_ekaterina')
    assert len(pcm) == 8000
    assert pcm.dtype == np.int16
    assert np.max(np.abs(pcm.astype(np.int32))) > 100


def test_invalid_voice_rejected_before_model_call():
    with pytest.raises(ValueError, match='Unsupported'):
        synthesize_silero_8k(FakeJitModel(), 'Здравствуйте', 'random')
    cfg = Config(tts_engine='silero', silero_speaker='unknown',
                 ari_password='secret', admin_token='x' * 32)
    with pytest.raises(ValueError, match='Silero'):
        cfg.validate()


def test_v3_launch_requires_ekaterina_and_never_changes_extension_200():
    shell = (Path(__file__).resolve().parents[1] / 'start-v3-wsl.sh').read_text()
    assert 'export TTS_ENGINE=silero' in shell
    assert 'export SILERO_SPEAKER=ru_ekaterina' in shell
    assert 'Refusing to start with Denis' in shell
    assert 'FREE_V3_ENGINE=piper' not in shell
    assert 'install-silero-v3-wsl.sh' in shell
    assert 'start-local-ai-wsl.sh' not in shell
    assert 'systemctl restart asterisk' not in shell


def test_offline_installer_requires_successful_voice_verification():
    """Incomplete or timed-out Silero downloads never activate a new voice."""
    folder = Path(__file__).resolve().parents[1]
    installer = (folder / 'install-silero-v3-wsl.sh').read_text()
    startup = (folder / 'start-v3-wsl.sh').read_text()
    assert 'ZVONKO_LOCAL_SILERO_FILE' in installer
    assert 'SILERO TEST PASSED' in installer
    assert "printf '%s" in installer
    assert 'v5_cis_base_nostress.ready' in installer
    assert 'v5_cis_base_nostress.ready' in startup
    assert 'Ekaterina voice is NOT installed/verified' in startup
    assert 'export TTS_ENGINE=silero' in startup
    assert 'export SILERO_SPEAKER=ru_ekaterina' in startup
    assert 'exit 1' in startup



def test_jit_rejects_multichannel_not_single_voice():
    """Only mono (1,N)/(N,1) or flat (N,) output is allowed."""
    import contextlib
    from types import SimpleNamespace
    from unittest.mock import patch

    class MultiChannelFake(FakeJitModel):
        def __call__(self, tokens, speaker_ids):
            return FakeAudio(np.ones((2, 48000), dtype=np.float32) * .2)

    with patch.dict(sys.modules, {'torch': SimpleNamespace(
            inference_mode=contextlib.nullcontext,
            Tensor=type('Tensor', (), {}), LongTensor=FakeTensor)}):
        with pytest.raises(RuntimeError, match=r"shape=\\(2, 48000\\)"):
            synthesize_silero_8k(
                MultiChannelFake(), 'Вопрос по VMD F60.', 'ru_ekaterina')
