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
from voice import quick_voice_reply, stop_requested, ulaw_decode
from v3_engine import stream_sales_response
from knowledge_vmd import load_catalog, catalog_context, product_answer

log = logging.getLogger('zvonko.v3')

# The local GPU sometimes needs several seconds to produce its first phrase.
# An explicit timeout prevents silent calls while Ollama is preparing a model.
V3_FIRST_PHRASE_TIMEOUT = 10.0
V3_NEXT_PHRASE_TIMEOUT = 4.0


class V3PhoneCall(PhoneCall):
    """Concurrent listening/response, interruptible short audio chunks."""

    def greeting(self)->str:
        return ('Здравствуйте! Я голосовой ИИ-помощник Звонко. '
                'Для какого объекта подбираете уборочную машину?')

    def __init__(self, manager: PhoneServer, channel_id: str, mode: str):
        super().__init__(manager, channel_id, mode)
        self.epoch = 0
        self.response_task: asyncio.Task | None = None
        self.utterance_started = 0.0
        # MicroSIP speaker echo was triggering false caller turns and cutting
        # off the greeting. V3 is half-duplex until proper AEC is available.
        self._capture_ready = False
        self._capture_blocked_until = 0.0
        self._processing_turn = False

    def _reset_capture(self) -> None:
        """Discard acoustic echo and partial VAD fragments between turns."""
        self.frame_bytes.clear()
        self.frames.clear()
        self.pre_roll.clear()
        self.voice_frames = 0
        self.silent_frames = 0

    async def say(self, text: str) -> None:
        """Temporarily mute speech recognition while our own RTP audio plays.

        This is deliberately half-duplex. Without acoustic echo cancellation,
        allowing barge-in can falsely detect our own TTS from PC speakers.
        """
        self._capture_ready = False
        self._reset_capture()
        try:
            await super().say(text)
        finally:
            self._capture_blocked_until = time.monotonic() + 0.7
            self._reset_capture()
            self._capture_ready = True

    def receive_audio(self, ulaw: bytes) -> None:
        if self.closed:
            return
        # Drop (not buffer) all local microphone audio while the assistant
        # speaks and during the 700ms echo tail after it finishes.
        if (self._processing_turn or not self._capture_ready or self.playing
                or time.monotonic() < self._capture_blocked_until):
            self._reset_capture()
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
                # Serialize a complete user question -> speech response.
                # Otherwise late microphone fragments repeatedly cancel the
                # first slow Ollama response, leaving the caller in silence.
                self._processing_turn = True
                self._capture_ready = False
                self._reset_capture()
                self.turn_task = asyncio.create_task(self.handle_turn(samples, turn))

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

            # Only one request at a time; half-duplex until the spoken answer
            # completes. Do not cancel an in-flight answer on raw mic noise.
            self.sales.observe(heard)
            self.history.append({'role': 'user', 'content': heard})
            if len(self.history) > 12:
                self.history = self.history[-12:]

            if stop_requested(heard) or self.sales.caller_declined:
                log.info('V3 reply path: caller requested stop')
                await self._speak_and_finish('Понял, не буду отвлекать. Всего доброго.', epoch)
                return

            canned = (product_answer(heard, self.sales) or quick_voice_reply(heard)
                      or fast_sales_reply(heard, self.sales, self.cfg.sales_offer))
            if canned:
                log.info('V3 reply path: verified catalogue or quick response')
                await self._speak_short(canned, epoch)
                return

            log.info('V3 reply path: local Qwen, awaiting first spoken phrase')
            await self._stream_answer(epoch)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception('V3 recognition/dispatch failed')
            if not self.closed:
                with contextlib.suppress(Exception):
                    await self.say('Не удалось обработать вопрос. Повторите, пожалуйста.')
        finally:
            # Never unlock the microphone before the completed answer.
            self._processing_turn = False
            if not self.closed:
                self._capture_ready = True
                self._reset_capture()
                self._capture_blocked_until = max(
                    self._capture_blocked_until, time.monotonic() + 0.7)
                log.info('V3 turn finished; microphone enabled after echo guard')

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
        """Answer a caller even if the local language model starts slowly."""
        started = time.monotonic()
        spoken: list[str] = []
        stream = None
        try:
            instruction = (
                catalog_context(self.history[-1]['content'], self.sales)
                + '\n' + sales_instruction(
                    self.sales, self.cfg.sales_offer, self.cfg.sales_goal)
            )
            stream = stream_sales_response(
                self.ai.http, self.cfg, list(self.history), instruction)
            try:
                first = await asyncio.wait_for(
                    anext(stream), timeout=V3_FIRST_PHRASE_TIMEOUT)
            except asyncio.TimeoutError:
                log.warning('V3 local Qwen silent for %.1fs; giving audible fallback',
                            V3_FIRST_PHRASE_TIMEOUT)
                await self.say(
                    'Мне нужно чуть больше времени на этот вопрос. '
                    'Повторите его, пожалуйста.')
                return
            except StopAsyncIteration:
                log.warning('V3 local Qwen returned no spoken text')
                await self.say('Повторите, пожалуйста, вопрос о технике.')
                return

            if self.closed or epoch != self.epoch:
                return
            log.info('V3 first answer text in %.2fs', time.monotonic()-started)
            spoken.append(first)
            await self.say(first)
            if self.closed or epoch != self.epoch:
                return

            # A second phrase is optional; never leave the phone silent again
            # while waiting for a slow model after the first sentence.
            try:
                second = await asyncio.wait_for(
                    anext(stream), timeout=V3_NEXT_PHRASE_TIMEOUT)
            except (StopAsyncIteration, asyncio.TimeoutError):
                second = None
            if second and not self.closed and epoch == self.epoch:
                spoken.append(second)
                await self.say(second)

            if spoken and not self.closed and self.epoch == epoch:
                self.history.append({'role': 'assistant',
                                     'content': ' '.join(spoken)})
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception('V3 local Qwen response failed')
            if not self.closed and self.epoch == epoch:
                with contextlib.suppress(Exception):
                    await self.say(
                        'Возникла техническая задержка. '
                        'Повторите, пожалуйста, вопрос.')
        finally:
            if stream is not None:
                # Drop any unused generator without leaking its HTTP stream.
                with contextlib.suppress(Exception):
                    await stream.aclose()

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
        ollama_model=os.environ.get('OLLAMA_MODEL_V3', 'qwen3.5:4b'),
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
