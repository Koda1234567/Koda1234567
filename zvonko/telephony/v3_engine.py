"""Zvonko 3: stream short, speakable sales replies from local Ollama.

Only locally hosted Ollama is used. No recording uploads or external calls.
"""
from __future__ import annotations
import asyncio
import json
import re
from collections.abc import AsyncIterator
from typing import Any
import aiohttp


class SpeechChunker:
    """Incremental short Russian turns: speak clause 1 before model finishes clause 2."""

    def __init__(self, max_chunks: int = 2, max_chars: int = 154):
        self.pending = ''
        self.sent = 0
        self.total_chars = 0
        self.max_chunks = max_chunks
        self.max_chars = max_chars

    @property
    def full(self) -> bool:
        return self.sent >= self.max_chunks or self.total_chars >= self.max_chars

    def _emit(self, words: str) -> str | None:
        text = re.sub(r'\s+', ' ', words).strip(' ,;:')
        if not text or self.full:
            return None
        room = self.max_chars - self.total_chars
        if len(text) > room:
            text = text[:room].rsplit(' ', 1)[0].strip(' ,;:') or text[:room]
        if not text:
            return None
        self.sent += 1
        self.total_chars += len(text)
        return text

    def feed(self, token: str) -> list[str]:
        if self.full:
            return []
        self.pending += token
        ready = []
        while self.pending and not self.full:
            # Prefer finishing a sentence or question rather than hard-cutting.
            punct = re.search(r'[.!?](?:\s|$)', self.pending)
            if punct and punct.end() >= 23:
                cut = punct.start() + 1
            elif len(self.pending) >= 78:
                # A first clause can already be spoken; keep its last whole word.
                prefix = self.pending[:78]
                cut = prefix.rfind(' ')
                if cut < 35:
                    break
            else:
                break
            part = self._emit(self.pending[:cut])
            self.pending = self.pending[cut:].lstrip()
            if part:
                ready.append(part)
        return ready

    def flush(self) -> list[str]:
        if self.full:
            return []
        part = self._emit(self.pending)
        self.pending = ''
        return [part] if part else []


async def stream_sales_response(
    http: aiohttp.ClientSession,
    cfg: Any,
    history: list[dict[str, str]],
    guidance: str,
) -> AsyncIterator[str]:
    """Generate one or two short phrases, exposing the first as early as possible.

    Uses Ollama NDJSON streaming. This is still sequential speech, not
    fully speech-to-speech. Tested latency must be measured on the user's PC.
    """
    prompt = (
        'Ты голосовой ИИ-помощник по B2B-продажам. Человек знает, что ты ИИ. '
        'Ты консультируешь по РЕАЛЬНЫМ моделям VMD. Твоя задача — понять объект, '
        'назвать подходящую модель из подтверждённой базы и объяснить конкретную пользу. '
        'Если спросили, что вы продаёте, назови категории техники и примеры моделей. '
        'Если спросили модель, ответь по её карточке. '
        'Не повторяй вопросы, на которые уже дан ответ. Не дави на покупателя. '
        'Максимум две короткие фразы и один естественный вопрос. '
        'Без markdown, таблиц, приветствий посреди беседы и длинных объяснений. '
        'Не придумывай фактов о наличии, ценах, происхождении, гарантиях, '
        'сертификации и сроках. Не обещай звонок, демонстрацию или КП, '
        'если никто их реально не оформил. '
        'Достоверные данные о предложении: ' + cfg.product_info[:1000] + '. '
        + guidance[:3600]
    )
    payload = {
        'model': cfg.ollama_model,
        'messages': [{'role': 'system', 'content': prompt}] + history[-8:],
        'stream': True,
        'keep_alive': '15m',
        'options': {'num_predict': 85, 'num_ctx': 3072, 'temperature': 0.35},
    }
    chunker = SpeechChunker()
    async with http.post(
        cfg.ollama_url.rstrip('/') + '/api/chat',
        json=payload,
        timeout=aiohttp.ClientTimeout(total=35, sock_read=20),
    ) as response:
        response.raise_for_status()
        async for line in response.content:
            if not line.strip():
                continue
            event = json.loads(line)
            if event.get('error'):
                raise RuntimeError('Local Ollama rejected streaming generation')
            piece = (event.get('message') or {}).get('content') or ''
            for phrase in chunker.feed(piece):
                yield phrase
                if chunker.full:
                    return
            if event.get('done'):
                break
    for phrase in chunker.flush():
        yield phrase
