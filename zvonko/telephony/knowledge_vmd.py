"""Grounded VMD product knowledge for local Zvonko phone calls.

No embedding service, external endpoint, sale/stock promises, or guessed pricing.
Model data lives in catalog_vmd.json and can be reviewed by the seller.
"""
from __future__ import annotations
from functools import lru_cache
from pathlib import Path
import json
import re
from typing import Any

CATALOG_PATH = Path(__file__).with_name('catalog_vmd.json')

def _norm(s: str) -> str:
    return re.sub(r'\s+', ' ', s.casefold().replace('ё', 'е').replace('‑', '-')).strip()

def _model_key(s: str) -> str:
    return re.sub(r'[^a-z0-9]', '', _norm(s).replace('vmd', ''))

@lru_cache(maxsize=1)
def load_catalog() -> dict[str, Any]:
    data=json.loads(CATALOG_PATH.read_text(encoding='utf-8'))
    if data.get('brand')!='VMD' or not isinstance(data.get('products'), list):
        raise ValueError('Invalid VMD catalog')
    seen=set()
    for model in data['products']:
        sku=model.get('sku')
        if not isinstance(sku,str) or not sku.startswith('VMD ') or sku in seen:
            raise ValueError('VMD catalog SKU missing or duplicated')
        seen.add(sku)
        if (not model.get('source','').startswith('https://vmdrussia.ru/')
            and model.get('source')!='supplier_price_list_2026-05-27'):
            raise ValueError('Unverified source for '+sku)
        if model.get('category') not in ('wet','dry','specialty','accessory'):
            raise ValueError('Invalid product category '+sku)
    return data

def _mentioned_products(text: str, products: list[dict]) -> list[dict]:
    raw=_norm(text)
    # Russian speech recognition often renders F as "ф", and BT as "бт".
    raw=raw.replace('в эм ди', 'vmd').replace('ви эм ди','vmd')
    raw=raw.replace('б ти', 'bt').replace('бт', 'bt').replace('ф ', 'f')
    result=[]
    for p in products:
        name=_norm(p['sku']).replace('vmd ','')
        variants={name, name.replace(' ','').replace('-',''),
                  name.replace('f','ф',1).replace('b','б')}
        if any(re.search(r'(?<![a-z0-9а-я])'+re.escape(v)+r'(?![a-z0-9а-я])',raw)
               for v in variants if len(v)>=2):
            result.append(p)
    return result

def _purpose(text: str, state: Any) -> str:
    t=_norm(text)
    wet_terms=('влажн','помыть','мыть','мойка','моечн','поломоеч','жидк','моем')
    dry_terms=('сух','подмет','песок','пыль','мусор','листва','стружк')
    wet=any(x in t for x in wet_terms)
    dry=any(x in t for x in dry_terms)
    if wet and dry:
        return 'mixed'
    if wet:
        return 'wet'
    if dry:
        return 'dry'
    if getattr(state,'purpose','') in ('wet','dry','mixed'):
        return state.purpose
    return 'unknown'

def _rank(products: list[dict], state: Any, purpose: str, text: str) -> list[dict]:
    area=getattr(state,'area_m2',None)
    site=_norm(getattr(state,'site_type',''))
    text=_norm(text)
    target_tier = ('compact' if area and area<=500 else
                   'medium' if area and area<=5000 else
                   'large' if area and area<=12000 else
                   'extra' if area else None)
    tier_order=['compact','medium','large','extra']
    def score(p):
        s=0
        if purpose in ('wet','dry') and p['category']==purpose:
            s+=20
        if purpose=='unknown' and p['category']=='wet':
            s+=2
        if target_tier in tier_order and p.get('tier') in tier_order:
            s+=8-3*abs(tier_order.index(target_tier)-tier_order.index(p['tier']))
        # Known case studies are evidence of real use, not machine capacity guarantees.
        if 'склад' in site and p['sku']=='VMD F60 B52' and (not area or 1500<=area<=4500):
            s+=6
        if 'медиц' in site and p['sku']=='VMD F-mop':
            s+=6
        if 'подмет' in text and p['category']=='dry':
            s+=4
        if 'сетев' in text and p['sku']=='VMD F60 C52':
            s+=8
        if 'аккумулятор' in text and p['sku']=='VMD F60 B52':
            s+=8
        return s
    return sorted(products,key=lambda p:(-score(p),p['sku']))

def shortlist(text: str, state: Any, count: int=3) -> list[dict]:
    products=load_catalog()['products']
    mentioned=_mentioned_products(text,products)
    if mentioned:
        return mentioned[:count]
    purpose=_purpose(text,state)
    if purpose=='mixed':
        # Never pretend a single machine automatically does both jobs.
        return _rank([p for p in products if p['category']=='wet'],state,'wet',text)[:2]+_rank(
            [p for p in products if p['category']=='dry'],state,'dry',text)[:1]
    if purpose=='unknown' and not getattr(state,'area_m2',None):
        return []
    selected=[p for p in products if p['category']==purpose] if purpose in ('wet','dry') else [p for p in products if p['category'] in ('wet','dry')]
    return _rank(selected,state,purpose,text)[:count]

def catalog_context(text: str, state: Any) -> str:
    """Source-backed context for each LLM generation; no blanket price claims."""
    data=load_catalog()
    models=shortlist(text,state)
    pieces=[
        'ПРОДАВЕЦ: независимый продавец оборудования VMD, не официальный сайт бренда.',
        'АССОРТИМЕНТ: поломоечные (влажная уборка), подметальные (сухая уборка), роторные и эскалаторные машины, аккумуляторы VMD.',
        'МОДЕЛИ (публично представлены): '+', '.join(x['sku'] for x in data['products'])+'.',
        'ТОЧНЫЕ ПРАВИЛА: не называй цену, наличие, сроки, скидку, гарантии или производительность без подтверждённых данных; кейс — не паспортная максимальная площадь.',
        'Подбор предварительный; нужны площадь, тип загрязнений, пол, проходы, режим уборки, питание и приоритет клиента.',
    ]
    for item in models:
        specs=item.get('specs',{})
        shown=[]
        for key,label,unit in [
            ('cleaning_width_mm','рабочая ширина','мм'),
            ('squeegee_width_mm','ширина скребка','мм'),
            ('clean_water_l','чистая вода','л'),
            ('waste_water_l','грязная вода','л'),
            ('waste_container_l','мусоросборник','л'),
            ('performance_m2_per_h','производительность по прайсу','м²/ч'),
            ('power','питание','')]:
            if key in specs:
                shown.append(f"{label}: {specs[key]} {unit}".strip())
        if 'performance_m2_per_h' in specs:
            shown.append('Тип показателя: '+specs.get('performance_type','прайс поставщика'))
        if specs.get('configs'):
            shown.append('Комплектации: '+ '; '.join(specs['configs']))
        pieces.append(f"МОДЕЛЬ {item['sku']}: {item['summary']} "
                      f"Параметры: {'; '.join(shown[:9])}. "
                      f"Пример применения: {', '.join(item['examples'])}. "
                      f"Источник: {item['source']}. "
                      'Цена и наличие пока не подтверждены.')
    if not models:
        pieces.append('Сначала уточни: нужна влажная мойка пола или сухой сбор мусора?')
    return '\n'.join(pieces)

def product_answer(text: str, state: Any) -> str | None:
    """Immediate, factual answers to direct catalogue questions."""
    t=_norm(text)
    products=load_catalog()['products']
    mentioned=_mentioned_products(text,products)
    pricing=any(term in t for term in ('цен','стоим','сколько стоит','прайс','в наличии','остаток'))
    if mentioned and pricing:
        return f"По {mentioned[0]['sku']} актуальную цену и наличие нужно проверить в прайсе поставщика. Для какого объекта рассматриваете?"
    if mentioned and any(term in t for term in ('что','расскаж','отлич','характерист','подойд','знаешь','модель','про ')):
        item=mentioned[0]
        return f"{item['sku']}: {item['summary']} Подскажите площадь и тип уборки."
    generic=any(term in t for term in (
        'что прода', 'что вы прода', 'чем торгу', 'что у вас есть','что можете предлож',
        'какой ассортимент', 'какие товары','что за техника', 'какое оборудование',
        'чем занимаетесь','какие модели','что предлагаете','какие машины'))
    if generic:
        return ('Мы продаём технику VMD: поломоечные, подметальные, роторные и эскалаторные машины, а также аккумуляторы. '
                'Вам нужна влажная или сухая уборка?')
    if pricing and not mentioned:
        return ('Точная стоимость зависит от модели и комплектации. '
                'Сначала подберём подходящую машину: нужна влажная или сухая уборка?')
    if any(term in t for term in ('подберите','подобрать','посоветуйте модель','какая модель подойд')) or (
        getattr(state,'area_m2',None) and any(term in t for term in ('склад','цех','полы','уборка'))):
        models=shortlist(text,state,count=2)
        if models:
            named=' или '.join(m['sku'] for m in models)
            return f"Предварительно можно рассмотреть {named}. Какая уборка нужна: влажная или сухая?"
    return None
