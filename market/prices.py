# -*- coding: utf-8 -*-
"""Telling a total price from a price per square metre.

New-build agencies quote €/m² and the extractor stored that figure as the
asking price, so a 108 m² house came out at €1 019. 235 of 830 sale offers --
28% -- were wrong that way, and every one of them looked plausible in
isolation: the number is real, it is in euros, it is on the page. Only the unit
is missing, and only price_raw carries it.

A per-m² quote is not a defect to discard. It is the more precise number of the
two, so it is kept as price_per_m2 and the total is derived where the area is
known. Where it is not, the total stays unknown rather than being invented --
which is the same rule the search applies to every other missing field.
"""
import re

PER_M2 = re.compile(
    r'(/|на\s+|per\s+)\s*(m2|m²|кв\.?\s*м|кв\.м|sq\.?\s*m|square\s*met)', re.I)


def is_per_m2(price_raw):
    return bool(price_raw and PER_M2.search(price_raw))


def normalise(price_eur, area_m2, price_raw):
    """Returns (price_eur, price_per_m2). Either may be None.

    Only the quoted text decides. A low number is not evidence on its own: a
    €14 000 parking space and a €1 100/m² flat are both small, and guessing
    from magnitude would mangle the cheap end of the real market.
    """
    if not is_per_m2(price_raw) or price_eur is None:
        return price_eur, (round(price_eur / area_m2, 2)
                           if price_eur and area_m2 else None)
    per_m2 = price_eur
    total = round(per_m2 * area_m2, 2) if area_m2 else None
    return total, per_m2


# A price split across lines. roneva renders the complex name and the price in
# one block, so "Възраждане 4" + "185 000 €" was read as 4 185 000 € -- a
# €185k flat priced at €4.19m, and 30 offers were wrong that way. The currency
# marker says which line is the price; nothing else does.
CURRENCY = re.compile(r'(€|EUR|лв\.?|BGN)', re.I)
DIGITS = re.compile(r'\d')


def price_line(price_raw):
    """The line of a multi-line price block that actually holds the price.

    Returns None when the text is a single line, or when no line can be
    singled out -- in which case the original value stands rather than being
    replaced by a guess.
    """
    if not price_raw or '\n' not in price_raw:
        return None
    lines = [ln.strip() for ln in price_raw.splitlines() if ln.strip()]
    if len(lines) < 2:
        return None
    priced = [ln for ln in lines if CURRENCY.search(ln) and DIGITS.search(ln)]
    if len(priced) == 1:
        return priced[0]
    if len(priced) > 1:
        # Two priced lines is genuinely ambiguous. Saying so leaves the stored
        # value alone, which is safer than picking one and being confidently
        # wrong about somebody's asking price.
        return None
    # No currency marker on any single line: the longest run of digits wins,
    # because a complex number ("4") is never the longest part of a price.
    numeric = [ln for ln in lines if DIGITS.search(ln)]
    if len(numeric) < 2:
        return None
    return max(numeric, key=lambda ln: len(DIGITS.findall(ln)))


# The first number in the line, and only that. Stripping every non-digit
# instead swept up the unit: "1 019 €/m2" became 10192, because the 2 of "m2"
# is a digit too.
NUMBER = re.compile(r'\d[\d\s\u00a0.,]*')


def value_of(text):
    """The number in a price line, ignoring spaces used as thousand marks."""
    if not text:
        return None
    match = NUMBER.search(text.replace('\u00a0', ' '))
    if not match:
        return None
    cleaned = match.group(0).replace(' ', '').rstrip('.,').replace(',', '.')
    if cleaned.count('.') > 1:
        cleaned = cleaned.replace('.', '', cleaned.count('.') - 1)
    # A trailing group of exactly three digits after a dot is a thousand mark,
    # not a decimal: "185.000" is 185 000, never 185.
    if '.' in cleaned and len(cleaned.split('.')[-1]) == 3:
        cleaned = cleaned.replace('.', '')
    try:
        return float(cleaned) or None
    except ValueError:
        return None
