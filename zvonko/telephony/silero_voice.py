"""Fully local Silero V5 CIS Base (MIT) voice for Zvonko extension 201.

The downloaded .jit file is the TorchScript *forward* model, not the Python
package model: it has no apply_tts method. Input uses integer symbol IDs and
speaker IDs documented in the authors' official v5_cis_base_jit.ipynb.
https://github.com/snakers4/silero-models/blob/master/v5_cis_base_jit.ipynb
"""
from __future__ import annotations

from pathlib import Path
import re
import numpy as np
from scipy.signal import resample_poly

SILERO_MODEL_URL = "https://models.silero.ai/models/tts/ru/v5_cis_base_nostress.jit"
# Official TorchScript model generates 48 kHz audio; telephony is 8 kHz.
SILERO_SAMPLE_RATE = 48000
# IDs are from the official Silero CIS JIT notebook, NOT the alphabetic order.
SILERO_SPEAKER_IDS = {
    "ru_eduard": 27,
    "ru_ekaterina": 28,
    "ru_kejilgan": 32,
}
SILERO_SPEAKERS = frozenset(SILERO_SPEAKER_IDS)
SILERO_SYMBOLS = "|||!'+,-.:;?hабвгдежзийклмнопрстуфхцчшщъыьэюяёєіїјўґғҕҗҙқҝҡңҥҫүұҳҷҹһӑӗәӝӟӣӥӧөӯӱӳӵӏ—… "
_SYMBOL_TO_ID = {symbol: i for i, symbol in enumerate(SILERO_SYMBOLS)}


def normalize_silero_text(text: str) -> str:
    """Make short sales prompts pronounceable using Cyrillic rather than Latin."""
    from voice import normalize_tts_text
    text = normalize_tts_text(text)
    text = re.sub(r"\bVMD\b", "ви эм ди", text, flags=re.IGNORECASE)
    text = re.sub(r"\bF\s*(?=[а-яё])", "эф ", text, flags=re.IGNORECASE)
    text = re.sub(r"[A-Za-z]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip(" ,;:-")
    return text or "Повторите, пожалуйста."


def silero_token_ids(text: str) -> list[int]:
    """TorchScript token IDs: BOS=2, EOS=1, matching official JIT example."""
    phrase = normalize_silero_text(text).lower()
    return [2] + [_SYMBOL_TO_ID[c] for c in phrase if c in _SYMBOL_TO_ID] + [1]


def load_silero_model(path: str):
    """Load the already-downloaded JIT model; never download at runtime."""
    import torch
    path = Path(path).expanduser()
    if not path.is_file() or path.stat().st_size < 1_000_000:
        raise RuntimeError(
            "Silero voice not installed. Run bash install-silero-v3-wsl.sh")
    torch.set_num_threads(min(4, max(1, torch.get_num_threads())))
    model = torch.jit.load(str(path), map_location="cpu")
    model.eval()
    return model


def synthesize_silero_8k(model, text: str, speaker: str) -> np.ndarray:
    """Return 8kHz mono PCM16 compatible with Asterisk ulaw RTP."""
    speaker_id = SILERO_SPEAKER_IDS.get(speaker)
    if speaker_id is None:
        raise ValueError("Unsupported Silero CIS voice")

    import torch
    # The .jit model is callable. It does not provide model.apply_tts().
    # Input is (1, sequence_length) of integer text tokens + (1,) speaker ID.
    text_tensor = torch.LongTensor(silero_token_ids(text)).unsqueeze(0)
    speaker_tensor = torch.LongTensor([speaker_id])
    with torch.inference_mode():
        speech = model(text_tensor, speaker_tensor)

    audio = np.asarray(speech.detach().cpu().numpy(), dtype=np.float32)
    if audio.ndim != 1 or audio.size == 0 or not np.isfinite(audio).all():
        raise RuntimeError("Silero produced invalid mono waveform")

    # 48kHz native => 8kHz for RTP: divide sample rate by six.
    pcm = resample_poly(audio, 1, 6)
    return np.clip(pcm * 32767, -32768, 32767).astype(np.int16)
