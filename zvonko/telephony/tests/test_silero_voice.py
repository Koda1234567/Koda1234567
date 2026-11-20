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
from silero_voice import normalize_silero_text, synthesize_silero_8k


class FakeAudio:
    def __init__(self, samples):
        self.samples = samples

    def detach(self):
        return self

    def cpu(self):
        return self

    def numpy(self):
        return self.samples


class FakeModel:
    def apply_tts(self, **kwargs):
        assert kwargs['speaker'] == 'ru_ekaterina'
        assert kwargs['sample_rate'] == 24000
        assert 'ви эм ди' in kwargs['text']
        return FakeAudio(np.sin(np.arange(24000, dtype=np.float32) / 17) * 0.4)


def test_free_voice_uses_cyrillic_and_normalizes_models():
    assert 'ви эм ди' in normalize_silero_text('VMD F60 B52')
    assert 'эф' in normalize_silero_text('VMD F60 B52')
    assert not any(c.isascii() and c.isalpha()
                   for c in normalize_silero_text('VMD F60 B52'))


def test_silero_uses_only_local_model_and_converts_to_rtp_pcm16():
    with patch.dict(sys.modules, {'torch': SimpleNamespace(inference_mode=contextlib.nullcontext,
                                                           Tensor=type('Tensor', (), {}))}):
        pcm = synthesize_silero_8k(FakeModel(), 'Вопрос по VMD F60.', 'ru_ekaterina')
    assert len(pcm) == 8000
    assert pcm.dtype == np.int16
    assert np.max(np.abs(pcm.astype(np.int32))) > 100


def test_invalid_voice_rejected_before_model_call():
    with pytest.raises(ValueError, match='Unsupported'):
        synthesize_silero_8k(FakeModel(), 'Здравствуйте', 'random')
    cfg = Config(tts_engine='silero', silero_speaker='unknown',
                 ari_password='secret', admin_token='x' * 32)
    with pytest.raises(ValueError, match='Silero'):
        cfg.validate()


def test_v3_launch_prefers_offline_silero_but_never_changes_extension_200():
    shell = (Path(__file__).resolve().parents[1] / 'start-v3-wsl.sh').read_text()
    assert 'FREE_V3_ENGINE=silero' in shell
    assert 'SILERO_SPEAKER' in shell
    assert 'install-silero-v3-wsl.sh' in shell
    assert 'start-local-ai-wsl.sh' not in shell
    assert 'systemctl restart asterisk' not in shell
