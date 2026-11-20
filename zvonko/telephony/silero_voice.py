"""Optional fully local Silero v5 CIS Base (MIT) voice for Zvonko extension 201.

No cloud TTS: inference uses a locally downloaded official TorchScript model.
Model reference: https://github.com/snakers4/silero-models (LICENSE_CIS).
"""
from __future__ import annotations

from pathlib import Path
import re
import numpy as np
from scipy.signal import resample_poly

SILERO_MODEL_URL = "https://models.silero.ai/models/tts/ru/v5_cis_base_nostress.jit"
SILERO_SPEAKERS = frozenset(("ru_ekaterina", "ru_eduard", "ru_kejilgan"))
SILERO_SAMPLE_RATE = 24000


def normalize_silero_text(text: str) -> str:
    """Make short sales prompts pronounceable using Cyrillic rather than Latin."""
    from voice import normalize_tts_text
    text = normalize_tts_text(text)
    text = re.sub(r"\bVMD\b", "ви эм ди", text, flags=re.IGNORECASE)
    text = re.sub(r"\bF\s*(?=[а-яё])", "эф ", text, flags=re.IGNORECASE)
    # Silero's Russian voice should never be fed unexplained Latin glyphs.
    text = re.sub(r"[A-Za-z]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip(" ,;:-")
    return text or "Повторите, пожалуйста."


def load_silero_model(path: str):
    """Load the already downloaded model; never download at runtime."""
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
    """Return 8kHz mono PCM16 compatible with existing Asterisk ulaw RTP."""
    if speaker not in SILERO_SPEAKERS:
        raise ValueError("Unsupported Silero CIS voice")
    phrase = normalize_silero_text(text)
    import torch
    with torch.inference_mode():
        speech = model.apply_tts(text=phrase, speaker=speaker,
                                 sample_rate=SILERO_SAMPLE_RATE)
    audio = np.asarray(speech.detach().cpu().numpy(), dtype=np.float32)
    if audio.ndim != 1 or audio.size == 0:
        raise RuntimeError("Silero produced invalid mono waveform")
    # The model emits floating PCM (-1..1) at 24kHz; telephone RTP uses 8k.
    pcm = resample_poly(audio, 1, 3)
    return np.clip(pcm * 32767, -32768, 32767).astype(np.int16)
