# -*- coding: utf-8 -*-
"""Recover the location of offers the header-driven parse left empty.

162 of ~1,135 active offers in the reference dataset have no location -- and
every single one of them has a populated `location_raw`. The parser found the
column and read it; it just could not map the value onto a known resort,
because the sheet said "Горица" or "BANG SARAY" or the name of a complex.

So we try again, harder, over location_raw + title + notes. What stays
unresolved is left unresolved on purpose: most of those really are inland
villages, and a village honestly marked "not one of the client's resorts" is a
*known miss* the scorer can rank down. Forcing it to the nearest coastal name
would be a lie that ranks it up.
"""
from sourcing.vendor import vocab

from crm.features import norm

# Longest alias first, so "свети влас" wins over a bare "влас" substring.
_ALIASES = sorted(
    ((norm(alias), canonical)
     for canonical, aliases in vocab.LOCATIONS.items()
     for alias in list(aliases) + [canonical]),
    key=lambda pair: -len(pair[0]))


# Words that qualify a resort rather than name it. "Свети" appears in three
# different places on this coast, so a bare "свети" identifies nothing.
_QUALIFIERS = {'sveti', 'svety', 'saint', 'st', 'sv', 'svetoy', 'svyatoy', 'свети',
               'св', 'святой', 'златни', 'zlatni', 'golden', 'слънчев', 'sunny',
               'солнечный', 'стар', 'old', 'нов', 'new', 'k', 's'}

# The distinctive half of each resort name -- "влас" for Свети Влас, "пясъци"
# for Златни пясъци -- so that a person writing "around Vlas" is understood.
_TOKENS = {}
for _canonical, _aliases in vocab.LOCATIONS.items():
    for _alias in list(_aliases) + [_canonical]:
        for _token in norm(_alias).split():
            if len(_token) >= 4 and _token not in _QUALIFIERS:
                _TOKENS.setdefault(_token, set()).add(_canonical)
# A token shared by two resorts identifies neither.
_TOKENS = {t: next(iter(c)) for t, c in _TOKENS.items() if len(c) == 1}


def resolve_location(*texts, loose=False):
    """Return a canonical resort name found in any of `texts`, else None.

    `loose` also accepts the distinctive half of a name on its own -- "Vlas",
    "Несебър" without its qualifier. It is deliberately **off** for crawler
    ingest, where a false positive would silently move 1,100 offers to the wrong
    town, and **on** for a brief a broker is about to read back and confirm.
    """
    haystack = norm(' '.join(str(t or '') for t in texts))
    if not haystack:
        return None
    for alias, canonical in _ALIASES:
        if alias and alias in haystack:
            return canonical
    if loose:
        for word in haystack.split():
            if word in _TOKENS:
                return _TOKENS[word]
    return None


def salvage(record):
    """Fill `location` on a parsed record in place. Returns True if recovered."""
    if record.get('location'):
        return False
    found = resolve_location(record.get('location_raw'),
                             record.get('title'),
                             record.get('notes'))
    if found:
        record['location'] = found
        record['location_salvaged'] = True
        return True
    return False


# --------------------------------------------------------------- pass two ----
# Mixed-script tokens are the signature of a homoglyph typo: someone typed
# "Sаint Vlas" with a Cyrillic 'а' sitting inside a Latin word, and no amount of
# alias matching will ever see it. Folding is applied ONLY to tokens that
# genuinely mix the two alphabets -- applying it everywhere would turn "море"
# into nonsense and break matching for the majority of sheets, which are
# Cyrillic throughout.
_HOMOGLYPHS = {'а': 'a', 'е': 'e', 'о': 'o', 'р': 'p', 'с': 'c', 'х': 'x',
               'у': 'y', 'к': 'k', 'м': 'm', 'т': 't', 'в': 'b', 'н': 'h'}
_CYRILLIC = set('абвгдежзийклмнопрстуфхцчшщъьюяыэё')
_LATIN = set('abcdefghijklmnopqrstuvwxyz')


def defang_homoglyphs(text):
    out = []
    for token in norm(text).split():
        letters = set(token)
        if letters & _CYRILLIC and letters & _LATIN:
            token = ''.join(_HOMOGLYPHS.get(ch, ch) for ch in token)
        out.append(token)
    return ' '.join(out)


# A complex is inferred from the corpus only when the evidence is one-sided.
# "Grand Village Park" is named by eight located offers, all of them in
# Кошарица, so the four rows that give no resort are safe to fill. "Къща с
# двор" matches five different towns at middling similarity -- that is a
# generic phrase, not a building, and guessing would put a flat in the wrong
# town on a client's shortlist. Ambiguity is left unresolved on purpose.
#
# Matching runs through the trigram index rather than string equality, because
# the unlocated row is usually the *longer* title: "Grand Kamelia Maisonette
# with sea view" has to find plain "Grand Kamelia".
SIMILARITY_FLOOR = 0.60      # below this, generic Bulgarian words start matching
DOMINANCE = 0.80             # one location must hold this share of the evidence
STRONG_SIMILARITY = 0.95     # a near-identical name convinces on its own
MIN_EVIDENCE = 2             # otherwise two corroborating offers are required


# Titles made only of property vocabulary are not building names. Two unrelated
# plots both titled "парцел" match each other at similarity 1.00, and the corpus
# would happily place one of them in the other's town. A title has to carry at
# least one word that actually names something before the corpus is asked.
GENERIC_TITLE_WORDS = {
    'partsel', 'parcel', 'plot', 'land', 'zemya', 'uchastok',
    'kashta', 'house', 'dom', 'dvor', 'yard', 'garden', 'gradina',
    'villa', 'vila', 'apartament', 'apartment', 'studio', 'studiya', 'atelie',
    'mezonet', 'maisonette', 'penthouse', 'pentkhaus', 'townhouse', 'taunkhaus',
    'etazh', 'floor', 'selo', 'village', 'grad', 'town', 'kvartal', 'raion',
    'sea', 'more', 'morska', 'morski', 'view', 'gledka', 'panorama',
    'beach', 'plazh', 'plazha', 'ezero', 'lake', 'reka', 'river', 'gora',
    'projekt', 'project', 'proekt', 'novo', 'new', 'stroitelstvo', 'stara',
    'tsentar', 'center', 'centre', 'metra', 'metar', 'ot', 'do', 'na', 'v', 's',
    'with', 'in', 'for', 'and', 'i', 'the', 'a', 'za', 'pri', 'nad', 'pod',
}


def is_distinctive(title_norm):
    """True when the title names something, rather than describing a category."""
    tokens = [t for t in (title_norm or '').split() if len(t) > 1]
    distinctive = [t for t in tokens if t not in GENERIC_TITLE_WORDS and len(t) >= 4]
    return bool(distinctive)


def infer_location_from_corpus(cursor, title_norm):
    """Ask the corpus where a complex is. Returns a location or None."""
    if not title_norm or not is_distinctive(title_norm):
        return None
    cursor.execute("""
        SELECT location, COUNT(*) AS n, MAX(similarity(title_norm, %(t)s)) AS best
        FROM sourcing_offer
        WHERE is_active AND location <> '' AND title_norm <> ''
          AND similarity(title_norm, %(t)s) >= %(floor)s
        GROUP BY location
        ORDER BY n DESC, best DESC
    """, {'t': title_norm, 'floor': SIMILARITY_FLOOR})
    rows = cursor.fetchall()
    if not rows:
        return None
    total = sum(r[1] for r in rows)
    location, count, best = rows[0]
    if count / total < DOMINANCE:
        return None                       # two towns claim it; say nothing
    if count >= MIN_EVIDENCE or best >= STRONG_SIMILARITY:
        return location
    return None


def salvage_corpus(offers_qs):
    """Second pass over offers still unlocated. Returns (recovered, details).

    Three more chances, strongest evidence first: the corpus's own view of where
    that complex is, a homoglyph-folded re-read of the raw text, and finally the
    sheet tab -- developer price lists routinely name the resort there ("Villa
    Maragrita Святой Влас") and it governs every row beneath it.
    """
    from django.db import connection

    recovered, details = 0, []
    with connection.cursor() as cursor:
        for offer in offers_qs:
            found = infer_location_from_corpus(cursor, offer.title_norm)
            source = 'корпус'
            if not found:
                found = resolve_location(defang_homoglyphs(
                    ' '.join([offer.location_raw or '', offer.title or ''])))
                source = 'изписване'
            if not found:
                found = resolve_location(offer.source_tab)
                source = 'име на таб'
            if not found:
                continue
            offer.location = found
            offer.location_salvaged = True
            offer.save(update_fields=['location', 'location_salvaged', 'updated_at'])
            details.append((offer.title[:40], found, source))
            recovered += 1
    return recovered, details
