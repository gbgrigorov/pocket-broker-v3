# -*- coding: utf-8 -*-
"""Reading the agencies' own spec tables.

Every site measured writes its facts as `label: value` under the heading --
"Площ:50.00 кв.м", "Этаж: 5", "Вид сделка:Под наем". That is worth far more
than pattern-matching free prose: the label says what the number means, which
is the difference between an asking price and a price per square metre.
"""
import re

PAIR = re.compile(r'([A-Za-zА-Яа-яЁёЂ-ќ][^:\n]{1,34}?)\s*:\s*([^\n:]{1,70})')

FIELDS = {
    'price_per_m2': (r'(цена|price|стоимост).{0,12}(за\s*)?(м2|м²|кв\.?\s*м|m2|sq)',),
    'price':        (r'^(цена|price|стоимост|цена на имота|asking)',),
    'area':         (r'^(площ|площадь|area|размер|квадратура|size|living area)',),
    'floor':        (r'^(етаж|этаж|floor|на етаж)',),
    'floors_total': (r'(общо етаж|всего этаж|total floors|етажност)',),
    'rooms':        (r'^(комнат|стаи|броя стаи|rooms|номер стаи)',),
    'bedrooms':     (r'^(спалн|bedroom|schlafzimmer|кол.{0,4}спал)',),
    'deal':         (r'(вид сделка|тип сделки|deal type|операция)',),
    'status':       (r'^(статус|състояние|состояние|status)',),
    'location':     (r'^(град|город|район|курорт|location|населено място|city|region)',),
    'view':         (r'(гледка|вид на море|вид из окна|view)',),
    'furnished':    (r'(мебел|обзавежд|обзаведен|furnish)',),
    'kind':         (r'^(вид имот|тип имота|тип недвижимости|property type|вид)',),
    'ref':          (r'^(код|реф|référ|ref|id|номер|артикул)',),
    'maintenance':  (r'(поддръжка|поддержка|такса|maintenance|service charge)',),
    'sea_distance': (r'(до море|до морето|разстояние до мор|distance to)',),
}

_COMPILED = {key: [re.compile(p, re.I) for p in pats] for key, pats in FIELDS.items()}

YES = re.compile(r'^(да|има|есть|yes|true|\+)', re.I)
NO = re.compile(r'^(не|няма|нет|no|false|-)', re.I)
GROUND = re.compile(r'(партер|цокол|ground|first floor|приземн)', re.I)


def pairs(text):
    """{field: raw value}, first occurrence winning.

    Order matters: `price_per_m2` is tested before `price` so that
    "Цена за м2: 909 €" never lands in the asking-price slot.
    """
    found = {}
    for raw_label, raw_value in PAIR.findall(text):
        label = raw_label.strip().lstrip('·•-–— ').strip()
        value = raw_value.strip()
        if not label or not value or len(label) < 2:
            continue
        for field, patterns in _COMPILED.items():
            if field in found:
                continue
            if any(p.search(label) for p in patterns):
                found[field] = value
                break
    return found


def boolean(value):
    if not value:
        return None
    if YES.match(value.strip()):
        return True
    if NO.match(value.strip()):
        return False
    return None


def floor_value(value, number):
    """'Партер' is a floor, and it is zero."""
    if value and GROUND.search(value):
        return 0
    return number(value)
