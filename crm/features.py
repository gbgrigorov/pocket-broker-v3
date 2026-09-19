# -*- coding: utf-8 -*-
"""Feature tokens and their matchers.

The crawler's vocabulary knows how to recognise a *view* column by its header.
It has no word list for what that column's values mean -- and the values are
free text in four languages ("море", "басейн", "вид на море/бассейн", "sea and
pool", "двор"). That gap is what this module fills.

Every matcher returns True, False or **None**, and None is the point: it means
the data does not say. A missing answer must never read as "no", because a flat
whose view column is simply empty is not a flat without a view -- it is a flat
we have to ring the agency about. That distinction is what produces the
"unverified" band instead of silently dropping good stock.
"""
import re
import unicodedata

from sourcing.vendor import vocab


def norm(text):
    """Casefold, strip accents and punctuation. Matching happens on this form."""
    if not text:
        return ''
    text = unicodedata.normalize('NFKD', str(text))
    text = ''.join(c for c in text if not unicodedata.combining(c))
    return re.sub(r'[^\w\s]+', ' ', text.casefold()).strip()


# token -> (Bulgarian label, positive words, negative words, fields to read)
#
# `fields` matters: a "pool" claim in the view column means the flat overlooks a
# pool, which is not the same as the complex having one -- but for a buyer
# browsing listings it is close enough to flag and far better than silence.
FEATURES = {
    'sea_view': ('гледка към морето',
                 ['море', 'морска', 'морски', 'sea', 'seaview', 'sea view', 'meer',
                  'на море', 'к морю', 'морето', 'панорама към морето', 'front line sea'],
                 ['без гледка', 'no sea', 'двор', 'улица', 'паркинг'],
                 ('view', 'title', 'notes')),
    'pool_view': ('гледка към басейна',
                  ['басейн', 'бассейн', 'pool', 'заведение басейн'], [],
                  ('view', 'title', 'notes')),
    'mountain_view': ('гледка към планината',
                      ['планина', 'горы', 'mountain', 'берг'], [], ('view', 'title', 'notes')),
    'pool': ('басейн в комплекса',
             ['басейн', 'бассейн', 'pool', 'swimming'], [],
             ('title', 'notes', 'view')),
    'furnished': ('обзаведен', [], [], ('furnished',)),          # a real boolean column
    'parking': ('паркомясто', vocab.PARKING_WORDS, [], ('title', 'notes', 'documents')),
    'act16': ('Акт 16',
              ['акт 16', 'акт16', 'act 16', 'act16', 'акт 16 готов', 'въведен в експлоатация'],
              ['акт 14', 'act 14', 'в строеж', 'предстои акт 16'],
              ('documents', 'notes', 'status', 'ready_date')),
    'new_build': ('ново строителство',
                  ['ново строителство', 'новостроящ', 'new build', 'новострой', 'в строеж'],
                  [], ('title', 'notes', 'documents')),
    'first_line': ('първа линия',
                   ['първа линия', 'first line', 'первая линия', 'frontline', 'front line',
                    'на плажа', 'on the beach'],
                   [], ('title', 'notes', 'view')),
    'lift': ('асансьор', ['асансьор', 'лифт', 'lift', 'elevator'], [], ('notes', 'title')),
    'garden': ('двор / градина',
               ['двор', 'градина', 'сад', 'garden', 'yard'], [], ('title', 'notes', 'view')),
}

FEATURE_CHOICES = [(token, label) for token, (label, *_rest) in FEATURES.items()]
FEATURE_LABELS = {token: label for token, (label, *_rest) in FEATURES.items()}


def match(token, offer):
    """True / False / None for one token against one offer dict.

    `offer` is a plain dict so this stays usable from the pure scoring engine,
    from ingest, and from tests, without importing Django models.
    """
    spec = FEATURES.get(token)
    if spec is None:
        return None
    _label, positives, negatives, fields = spec

    if token == 'furnished':
        return offer.get('furnished')            # already a nullable boolean

    haystack = norm(' '.join(str(offer.get(f) or '') for f in fields))
    if not haystack.strip():
        return None                              # the data does not say

    if any(norm(w) in haystack for w in negatives):
        return False
    if any(norm(w) in haystack for w in positives):
        return True

    # The fields carry text, and none of it mentions this feature. For a view
    # token that is a real "no" -- the sheet described the view and it is not
    # the sea. For everything else, absence of evidence is not evidence.
    if token in ('sea_view', 'pool_view', 'mountain_view') and norm(offer.get('view') or ''):
        return False
    return None


def resolve(offer):
    """All decidable tokens for an offer. Undecidable ones are simply absent."""
    out = {}
    for token in FEATURES:
        value = match(token, offer)
        if value is not None:
            out[token] = bool(value)
    return out


def describe(tokens):
    return ', '.join(FEATURE_LABELS.get(t, t) for t in tokens)
