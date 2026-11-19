"""Conservative B2B sales dialogue guidance for a consent-based AI phone pilot.

All product facts are provided by the client in Config; never invent prices,
countries of origin, availability, demos, discounts or warranties.
"""
from __future__ import annotations
from dataclasses import dataclass, field
import re

_DECLINE = re.compile(r'\b(не\s+интересно|не\s+нужно|ничего\s+не\s+надо|откажусь|не\s+актуально|не\s+звоните|до\s+свидания)\b', re.I)
_WHAT = re.compile(r'\b(кто\s+вы|что\s+предлагаете|что\s+за\s+компания|чем\s+занимаетесь)\b', re.I)
_PRICE = re.compile(r'\b(цена|цену|стоимость|сколько\s+стоит|прайс|почём)\b', re.I)
_CLEANING = re.compile(r'\b(клининг|подрядчик|убирает\s+подрядчик|на\s+аутсорсе)\b', re.I)
_BUDGET = re.compile(r'\b(нет\s+денег|нет\s+бюджета|дорого|дороговато)\b', re.I)
_CHINA = re.compile(r'\b(китайск\w*|из\s+китая|китайская)\b', re.I)
_SITE = re.compile(r'\b(склад\w*|цех\w*|паркинг\w*|производств\w*|магазин\w*|торгов\w*\s+зал\w*|офис\w*)\b', re.I)
_FLOOR = re.compile(r'\b(плитк\w*|бетон\w*|керамогранит\w*|наливн\w*\s+пол\w*)\b', re.I)
_AREA = re.compile(r'(\d[\d\s]{0,9})\s*(?:м2|м²|квадратн|кв\.?\s?м)', re.I)

@dataclass
class SalesState:
    turn: int = 0
    area_m2: int | None = None
    objection: str = ''
    site_type: str = ''
    floor_type: str = ''
    caller_declined: bool = False
    # Never automatically book anything or send data to external systems.
    requested_handoff: bool = False

    def observe(self, heard: str) -> None:
        self.turn += 1
        m = _AREA.search(heard)
        if m:
            digits = re.sub(r'\D', '', m.group(1))
            if digits:
                area = int(digits)
                if 1 <= area <= 10000000:
                    self.area_m2 = area
        if _SITE.search(heard) and not self.site_type:
            self.site_type = _SITE.search(heard).group(0).casefold()
        if _FLOOR.search(heard) and not self.floor_type:
            self.floor_type = _FLOOR.search(heard).group(0).casefold()
        if _DECLINE.search(heard):
            self.caller_declined = True
        if _BUDGET.search(heard):
            self.objection = 'budget'
        elif _CLEANING.search(heard):
            self.objection = 'outsourced_cleaning'
        elif _CHINA.search(heard):
            self.objection = 'origin_or_reliability'
        if re.search(r'\b(свяжите|перезвоните|менеджер|предложение|коммерческое)\b', heard, re.I):
            self.requested_handoff = True

def sales_instruction(state: SalesState, offer: str, goal: str) -> str:
    """Per-turn sales coaching fed to a local small language model."""
    stage = ('первичное выяснение задачи' if state.turn <= 2
             else 'подбор решения' if state.turn <= 5
             else 'обсуждение следующего шага')
    facts = f'Известная площадь: {state.area_m2} кв. м. ' if state.area_m2 else 'Площадь пока неизвестна. '
    if state.site_type:facts += f'Тип объекта: {state.site_type}. '
    if state.floor_type:facts += f'Покрытие: {state.floor_type}. '
    if state.objection:facts += f'Возражение: {state.objection}. '
    return (
      'Твоя роль: доброжелательный B2B-менеджер по продажам, ты явно представляешься ИИ. '
      f'Продукт: {offer[:140]}. Цель беседы: {goal[:140]}. '
      f'Текущий этап: {stage}. {facts}'
      'Не устраивай допрос: один короткий вопрос за раз. '
      'Сначала выясни объект, задачу и критерий выбора; затем предложи релевантный следующий шаг. '
      'Если клиент уже ответил на вопрос, не повторяй его. '
      'Если клиент не готов, признай это и вежливо заверши разговор. '
      'Не заявляй, что встреча, заявка, звонок или КП оформлены — это может делать только человек. '
      'Никаких выдуманных цен, наличия, гарантии, скидок или обещаний экономии. '
      'Избегай агрессивного давления и заученных скриптов. '
      'Ответ одним предложением, максимум двадцать слов и один вопрос.'
    )

def fast_sales_reply(heard: str, state: SalesState, offer: str) -> str | None:
    """Useful no-LLM replies that never assert unverified product details."""
    if state.caller_declined:
        return 'Понял, не буду отвлекать. Всего доброго!'
    if _WHAT.search(heard):
        return f'Я Звонко, голосовой ИИ-консультант по теме «{offer[:65]}». Подскажите, какая у вас задача?'
    if _CLEANING.search(heard):
        return 'Понимаю, у вас уже работает клининговая компания. Вы рассматриваете собственную технику или пока неактуально?'
    if _BUDGET.search(heard):
        if state.area_m2:
            return 'Понимаю, бюджет важен. А сейчас убираете вручную или машиной?'
        return 'Понимаю. Чтобы не предлагать лишнего, какая примерно площадь уборки?'
    if _CHINA.search(heard):
        return 'Сомнения понятны. Что для вас важнее: сервис, ресурс или гарантия?'
    if _PRICE.search(heard):
        if state.area_m2:
            return 'Для точной цены нужен подбор модели. Какое покрытие пола на объекте?'
        return 'Цена зависит от задачи и модели. Какая примерно площадь помещения?'
    if state.requested_handoff and re.search(r'\b(свяжите|менеджер|перезвоните)\b', heard, re.I):
        return 'Сейчас я не могу соединить с менеджером. Могу помочь сформулировать запрос для него.'
    if state.area_m2 and _AREA.search(heard) and not state.floor_type:
        return 'Понял площадь. А какое покрытие пола на объекте?'
    if state.site_type and _SITE.search(heard) and not state.area_m2:
        return 'Понял тип объекта. Какая примерно площадь уборки?'
    if state.floor_type and _FLOOR.search(heard):
        return 'Спасибо, покрытие понятно. Убираете вручную или уже используете машину?'
    return None
