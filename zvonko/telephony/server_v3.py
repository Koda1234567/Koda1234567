"""Isolated Zvonko v3 phone prototype: Stasis(zvonko3) / local extension 201.

Reuses established Asterisk/RTP plumbing. No outbound dialler.
Legacy Stasis(zvonko) / extension 200 remains operational.
"""
from __future__ import annotations

import asyncio
import contextlib
from dataclasses import replace
import logging
import os
import time

from aiohttp import web
import numpy as np

from config import Config
from sales import fast_sales_reply, sales_instruction
from server import PhoneCall, PhoneServer, create_app
from voice import quick_voice_reply, rms, stop_requested, ulaw_decode
from v3_engine import stream_sales_response
from knowledge_vmd import load_catalog, catalog_context, product_answer

log = logging.getLogger('zvonko.v3')


class V3PhoneCall(PhoneCall):
    """Concurrent listening/response, interruptible short audio chunks."""

    def greeting(self)->str:
        return ('Здравствуйте! Это Звонко, голосовой ИИ-консультант. '
                'Мы подбираем поломоечные и подметальные машины VMD. '
                'Какая уборка нужна вам?')

    def __init__(self, manager: PhoneServer, channel_id: str, mode: str):
        super().__init__(manager, channel_id, mode)
        self.epoch = 0
        self.response_task: asyncio.Task | None = None
        self.utterance_started = 0.0

    def _interrupt_outgoing(self) -> None:
        """React to sustained caller voice, not an isolated packet of echo."""
        self.interrupt.set()
        if self.response_task and not self.response_task.done():
            self.response_task.cancel()

    def receive_audio(self, ulaw: bytes) -> None:
        if self.closed:
            return
        self.frame_bytes.extend(ulaw)
        while len(self.frame_bytes) >= 160:
            pcm = ulaw_decode(bytes(self.frame_bytes[:160]))
            del self.frame_bytes[:160]
            try:
                speaking = self.ai.speech_frame(pcm)
            except Exception:
                log.exception('VAD failed')
                return
            self.pre_roll.append(pcm)

            if speaking:
                self.voice_frames += 1
                self.silent_frames = 0
                # MicroSIP may leak TTS back into the mic; require >120ms
                # of fairly strong voice before allowing barge-in.
                if (self.playing and self.voice_frames >= 7 and rms(pcm) >= 450):
                    self._interrupt_outgoing()
            elif self.frames:
                self.silent_frames += 1

            if not self.frames and self.voice_frames >= 3:
                self.frames = list(self.pre_roll)
                self.utterance_started = time.monotonic()
                self.epoch += 1
            elif self.frames:
                self.frames.append(pcm)

            # ~440ms silence, but never endpoint an extremely short noise burst.
            if self.frames and ((self.silent_frames >= 22 and len(self.frames) >= 19)
                                or len(self.frames) >= 750):
                samples = np.concatenate(self.frames)
                turn = self.epoch
                if self.turn_task and not self.turn_task.done():
                    self.turn_task.cancel()
                self.turn_task = asyncio.create_task(self.handle_turn(samples, turn))
                self.frames = []
                self.voice_frames = 0
                self.silent_frames = 0
                self.pre_roll.clear()

            if not speaking and not self.frames:
                self.voice_frames = 0

    async def handle_turn(self, samples: np.ndarray, epoch: int) -> None:
        """Recognise speech, then delegate response without blocking the mic."""
        try:
            started = time.monotonic()
            heard = await self.ai.transcribe(samples)
            if not heard or self.closed or epoch != self.epoch:
                return
            log.info('V3 recognized utterance in %.2fs, chars=%d',
                     time.monotonic() - started, len(heard))

            # Stop any outdated spoken greeting or answer before replying.
            if self.play_task and not self.play_task.done():
                self.interrupt.set()
                self.play_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self.play_task
            if self.response_task and not self.response_task.done():
                self.response_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self.response_task

            self.sales.observe(heard)
            self.history.append({'role': 'user', 'content': heard})
            if len(self.history) > 12:
                self.history = self.history[-12:]

            if stop_requested(heard) or self.sales.caller_declined:
                self.response_task = asyncio.create_task(
                    self._speak_and_finish('Понял, не буду отвлекать. Всего доброго.', epoch))
                return

            canned = (product_answer(heard, self.sales) or quick_voice_reply(heard)
                      or fast_sales_reply(heard, self.sales, self.cfg.sales_offer))
            if canned:
                self.response_task = asyncio.create_task(
                    self._speak_short(canned, epoch))
                return

            self.response_task = asyncio.create_task(self._stream_answer(epoch))
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception('V3 recognition/dispatch failed')

    async def _speak_short(self, reply: str, epoch: int) -> None:
        if self.closed or self.epoch != epoch:
            return
        try:
            self.history.append({'role': 'assistant', 'content': reply})
            await self.say(reply)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception('V3 short reply failed')

    async def _speak_and_finish(self, reply: str, epoch: int) -> None:
        try:
            await self._speak_short(reply, epoch)
            if not self.closed and epoch == self.epoch:
                await self.close(hangup=True)
        except asyncio.CancelledError:
            raise

    async def _stream_answer(self, epoch: int) -> None:
        started = time.monotonic()
        spoken = []
        try:
            instruction = (catalog_context(self.history[-1]['content'], self.sales)
                           + '\n' + sales_instruction(
                               self.sales, self.cfg.sales_offer, self.cfg.sales_goal))
            async for phrase in stream_sales_response(
                    self.ai.http, self.cfg, list(self.history), instruction):
                if self.closed or epoch != self.epoch:
                    return
                if not spoken:
                    log.info('V3 first answer text in %.2fs', time.monotonic()-started)
                spoken.append(phrase)
                await self.say(phrase)
            if spoken and not self.closed and self.epoch == epoch:
                self.history.append({'role': 'assistant', 'content': ' '.join(spoken)})
            elif not spoken and not self.closed and self.epoch == epoch:
                await self.say('Уточните, пожалуйста, какая задача у вас сейчас?')
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception('V3 streaming answer failed')
            if not self.closed and self.epoch == epoch:
                with contextlib.suppress(Exception):
                    await self.say('Извините, возникла техническая заминка. Повторите вопрос.')

    async def close(self, hangup: bool = False) -> None:
        if self.response_task and self.response_task is not asyncio.current_task():
            self.response_task.cancel()
        await super().close(hangup=hangup)


class V3PhoneServer(PhoneServer):
    def __init__(self, cfg: Config):
        super().__init__(cfg)
        self.call_class = V3PhoneCall


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    base = Config()
    cfg = replace(
        base,
        ari_app='zvonko3',
        admin_port=8767,
        enable_test_outbound=False,
        ollama_model=os.environ.get('OLLAMA_MODEL_V3', 'qwen2.5:3b'),
    )
    cfg.validate()
    data=load_catalog()
    log.info('VMD catalog loaded: %d verified model cards; no unverified prices',
             len(data['products']))
    server = V3PhoneServer(cfg)
    await server.start()
    runner = web.AppRunner(create_app(server))
    await runner.setup()
    await web.TCPSite(runner, host=cfg.admin_host, port=cfg.admin_port).start()
    log.info('Zvonko V3 ready. Test local extension 201; 200 untouched.')
    try:
        await asyncio.Event().wait()
    finally:
        await runner.cleanup()
        await server.stop()


if __name__ == '__main__':
    asyncio.run(main())
