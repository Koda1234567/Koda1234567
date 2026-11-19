import os,sys
sys.path.insert(0,os.path.dirname(os.path.dirname(__file__)))
from sales import SalesState,sales_instruction,fast_sales_reply

OFFER='поломоечные машины VMD'

def test_qualifies_area_without_inventing_more_details():
    state=SalesState()
    state.observe('Для склада около 1200 м²')
    assert state.area_m2==1200
    assert '1200 кв. м' in sales_instruction(state,OFFER,'консультация')
    assert state.turn==1

def test_price_reply_asks_for_task_instead_of_inventing_quote():
    state=SalesState()
    state.observe('А сколько стоит?')
    reply=fast_sales_reply('А сколько стоит?',state,OFFER)
    assert 'зависит' in reply.lower()
    assert 'площад' in reply.lower()
    assert '₽' not in reply

def test_outsourced_cleaning_objection_is_respected():
    state=SalesState()
    state.observe('У нас клининг, своя техника не нужна')
    reply=fast_sales_reply('У нас клининг',state,OFFER)
    assert 'клининг' in reply
    assert state.objection=='outsourced_cleaning'

def test_decline_not_followed_by_more_sales():
    state=SalesState()
    state.observe('Не интересно. Спасибо')
    assert state.caller_declined
    reply=fast_sales_reply('Не интересно. Спасибо',state,OFFER)
    assert 'всего доброго' in reply.lower()

def test_handoff_is_request_not_fake_booking():
    state=SalesState()
    state.observe('Пусть менеджер перезвонит')
    assert state.requested_handoff
    prompt=sales_instruction(state,OFFER,'консультация')
    assert 'Не заявляй, что встреча, заявка' in prompt

def test_offer_context_is_configurable():
    state=SalesState()
    assert 'оборудование' in sales_instruction(state,'оборудование','согласовать консультацию')
