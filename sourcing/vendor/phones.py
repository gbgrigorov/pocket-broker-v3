# -*- coding: utf-8 -*-
"""Bulgarian phone-number extraction, shared by the registry parser and the
agency profiler.

The contact cells in these sheets are free text holding several numbers, notes
and names at once, and they sit next to columns full of prices and areas. So the
job is two-sided: find every number written in any of the local conventions
(+359…, 00359…, 0888…, or a bare 888…), and reject the many number-shaped
strings that are not phone numbers at all.
"""
import re

# a run of digits and separators long enough to be a phone number
CANDIDATE = re.compile(r'(?:\+|00)?\d[\d\s\-./()]{7,18}\d')

# +359 then 9 digits. Mobile: 87/88/89/98/99. Landline: 2 (Sofia), 32, 52, 56…
VALID = re.compile(r'^\+359(?:8[7-9]\d{7}|9[89]\d{7}|[2-7]\d{6,8})$')


def normalise(raw):
    """One candidate string -> '+359XXXXXXXXX', or None if it is not a number."""
    d = re.sub(r'\D', '', raw or '')
    if not d:
        return None
    if d.startswith('00'):
        d = d[2:]
    if d.startswith('359'):
        pass
    elif d.startswith('0'):
        d = '359' + d.lstrip('0')
    elif len(d) == 9 and d[0] in '89':
        d = '359' + d                     # '887 357 142', written without the 0
    elif len(d) == 8 and d[0] in '2345678':
        d = '359' + d                     # landline without the area 0
    else:
        return None
    num = '+' + d[:12]
    # long zero runs mean a price and an area got glued together, not a number
    if re.search(r'0{4}', num):
        return None
    return num if VALID.match(num) else None


def extract(*texts):
    """All distinct valid numbers found across the given free-text cells."""
    out = []
    for text in texts:
        if not text:
            continue
        for m in CANDIDATE.finditer(str(text).replace('\n', ' ')):
            num = normalise(m.group())
            if num and num not in out:
                out.append(num)
    return out
