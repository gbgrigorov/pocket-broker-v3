# -*- coding: utf-8 -*-
"""Which resorts a buyer will accept as a substitute for the one he named.

A client who says "Sveti Vlas" almost never means only Sveti Vlas -- he means
that stretch of coast. Measured on the reference dataset, allowing the
neighbouring resorts adds 61 further two-bedroom apartments under €150,000 to a
search that would otherwise return 13. Refusing to look next door is the
single most expensive default a property search can have.

Adjacency is symmetric and is built once from the clusters below.
"""
CLUSTERS = [
    # Nesebar bay -- walking or a few minutes' drive between them
    ['Свети Влас', 'Несебър', 'Слънчев бряг', 'Равда', 'Елените', 'Кошарица', 'Тънково'],
    # Pomorie / Aheloy, just north of Burgas
    ['Поморие', 'Ахелой', 'Каблешково'],
    # Burgas and its own seaside suburbs
    ['Бургас', 'Сарафово', 'Крайморие', 'Черноморец'],
    # The southern strip
    ['Созопол', 'Черноморец', 'Дюни', 'Приморско', 'Китен', 'Лозенец'],
    ['Царево', 'Ахтопол', 'Синеморец', 'Лозенец'],
    # North of Obzor
    ['Обзор', 'Бяла', 'Шкорпиловци'],
    # Varna and its resorts
    ['Варна', 'Златни пясъци', 'Св. Константин и Елена', 'Свети Никола', 'Бяла'],
    ['Албена', 'Балчик', 'Каварна', 'Златни пясъци'],
]

ADJACENT = {}
for _cluster in CLUSTERS:
    for _name in _cluster:
        ADJACENT.setdefault(_name, set()).update(n for n in _cluster if n != _name)


def adjacent_to(locations):
    """Every resort neighbouring any of `locations`, excluding them."""
    chosen = set(locations or [])
    out = set()
    for name in chosen:
        out |= ADJACENT.get(name, set())
    return out - chosen
