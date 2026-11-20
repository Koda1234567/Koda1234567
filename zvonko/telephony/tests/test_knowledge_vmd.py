"""Product knowledge must answer with real VMD SKUs and never invent prices."""
import os
import sys
sys.path.insert(0,os.path.dirname(os.path.dirname(__file__)))
from sales import SalesState
from knowledge_vmd import load_catalog, catalog_context, shortlist, product_answer


def test_official_catalog_has_real_wet_and_dry_models():
    d=load_catalog()
    assert d['brand']=='VMD'
    assert len(d['products'])>=13
    names={p['sku'] for p in d['products']}
    assert {'VMD F-mop','VMD F60 C52','VMD F60 B52','VMD F60 BT52',
            'VMD F80 BT58','VMD F80 BT70','VMD F130 BT80','VMD F200 BT90',
            'VMD S1','VMD S2','VMD C100','VMD C120P','VMD C200'}<=names
    assert all(p['price_rub'] is None for p in d['products'])
    assert all(p['stock_status']=='не проверено' for p in d['products'])


def test_buyer_asks_what_you_sell():
    state=SalesState()
    for utterance in ('Что вы продаёте?', 'Что продаешь?',
                      'Что у вас есть?', 'Какие модели?', 'Какое оборудование?'):
        reply=product_answer(utterance,state)
        assert reply and 'VMD' in reply
        assert 'поломоечные' in reply and 'подметальные' in reply


def test_specific_machine_question_uses_only_verified_card():
    state=SalesState()
    info=product_answer('Расскажи про VMD F60 B52',state)
    assert 'VMD F60 B52' in info
    assert 'влажной' in info
    price=product_answer('Сколько стоит VMD F60 B52?',state)
    assert 'цену' in price
    assert not any(ch.isdigit() for ch in price.replace('F60','').replace('B52',''))


def test_spoken_sku_russian_letters():
    state=SalesState()
    info=product_answer('Что за ф60 б52',state)
    assert info and 'F60 B52' in info


def test_use_case_shortlist_is_relevant():
    state=SalesState()
    state.observe('У нас склад 2500 квадратов')
    wet=shortlist('Нужна влажная уборка на складе',state)
    assert wet
    assert wet[0]['category']=='wet'
    assert any(x['sku']=='VMD F60 B52' for x in wet)
    dry=shortlist('Нужно сухое подметание песка и пыли',state)
    assert dry and all(x['category']=='dry' for x in dry)
    context=catalog_context('Нужна влажная уборка на складе',state)
    assert 'VMD F60 B52' in context
    assert 'Цена и наличие пока не подтверждены.' in context


def test_no_capacity_equals_case_study():
    state=SalesState()
    state.observe('Склад 2500 квадратов')
    context=catalog_context('влажная уборка склада',state)
    assert 'кейс' in context.lower()
    assert 'кейс — не паспортная максимальная площадь' in context
