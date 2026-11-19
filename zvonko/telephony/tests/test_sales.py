import os,sys
sys.path.insert(0,os.path.dirname(os.path.dirname(__file__)))
from sales import SalesState,sales_instruction,fast_sales_reply,parse_spoken_area

OFFER='профессиональные поломоечные машины VMD'

def test_sales_observe_location_floor_area():
    s=SalesState()
    s.observe('У нас склад 2500 кв. м, бетонный пол')
    assert s.area_m2 == 2500
    assert 'склад' in s.site_type
    assert 'бетон' in s.floor_type
    assert s.turn == 1
    prompt=sales_instruction(s,OFFER,'подбор')
    assert '2500' in prompt and 'склад' in prompt and 'бетон' in prompt
    assert 'Никаких выдуманных цен' in prompt

def test_sales_objections_are_short_and_respectful():
    s=SalesState()
    s.observe('У нас уборку делает подрядчик, ничего не покупаем')
    assert s.objection == 'outsourced_cleaning'
    assert 'подряд' in fast_sales_reply('У нас клининг',s,OFFER).lower()
    s.observe('Это дорого, у нас нет бюджета')
    assert s.objection == 'budget'
    assert 'бюджет' in fast_sales_reply('Дорого',s,OFFER).lower()
    s.observe('Не доверяю китайской технике')
    assert s.objection == 'origin_or_reliability'
    assert 'сервис' in fast_sales_reply('китайская',s,OFFER).lower()

def test_no_price_invention_and_qualified_lead():
    s=SalesState()
    s.observe('Какая у вас цена?')
    response=fast_sales_reply('Какая у вас цена?',s,OFFER)
    assert 'площад' in response.lower()
    assert not any(x.isdigit() for x in response)
    s.observe('500 квадратных метров')
    assert s.area_m2==500
    assert 'покрыти' in fast_sales_reply('500 квадратных метров',s,OFFER).lower()

def test_decline_no_pressure():
    s=SalesState()
    s.observe('Мне не интересно, до свидания')
    assert s.caller_declined
    assert 'всего доброго' in fast_sales_reply('Мне не интересно',s,OFFER).lower()

def test_handoff_does_not_claim_booking():
    s=SalesState()
    s.observe('Свяжите меня с менеджером')
    assert s.requested_handoff
    assert 'не заявляй' in sales_instruction(s,OFFER,'подбор').lower()


def test_spoken_area_understands_real_phone_language():
    assert parse_spoken_area('У нас склад две тысячи пятьсот квадратов') == 2500
    assert parse_spoken_area('Площадь полторы тысячи квадратных метров') == 1500
    assert parse_spoken_area('Убираем тысячу двести квадратов') == 1200
    assert parse_spoken_area('У нас 2500 квадратов') == 2500
    assert parse_spoken_area('Мой номер 89112223344') is None
    state=SalesState()
    state.observe('Склад две тысячи пятьсот квадратов')
    assert state.area_m2==2500
    assert 'покрыти' in fast_sales_reply(
        'две тысячи пятьсот квадратов',state,OFFER).lower()
