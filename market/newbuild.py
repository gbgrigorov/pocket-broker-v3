# -*- coding: utf-8 -*-
"""Is this a new build, and how far along is it?

41% of the Varna stock mentions new construction somewhere in its text and none
of it was searchable: a buyer who does not want to wait two years for Акт 16
had no way to exclude it, and one who specifically wants off-plan had no way to
find it. Agencies do not publish a structured field for this -- it lives in the
title, in emoji-laden marketing copy, and in the description.

The Bulgarian construction milestones, in order:

    Акт 14   the frame is up and accepted. Furthest from habitable.
    Акт 15   the building is finished and handed over by the builder.
    Акт 16   permission to use it. Only here does it become a home you can
             legally live in -- and only here does a preliminary contract
             turn into something a buyer actually owns.

"Пред Акт 16" means the building has NOT reached it yet, which is the opposite
of what a careless reader takes from seeing the words "Акт 16". The order of
the checks below is therefore load-bearing.
"""
import re

# Checked in this order: a "pre-X" phrase must win over the bare milestone it
# contains, or "Пред Акт 16" reads as a finished building.
STAGES = (
    ('pre_act16', re.compile(r'пред\s*акт\s*-?\s*16|преди\s*акт\s*-?\s*16', re.I), 'Пред Акт 16'),
    ('pre_act14', re.compile(r'пред\s*акт\s*-?\s*14', re.I), 'Пред Акт 14'),
    ('act16', re.compile(r'акт\s*-?\s*16|акт16', re.I), 'Акт 16'),
    ('act15', re.compile(r'акт\s*-?\s*15|акт15', re.I), 'Акт 15'),
    ('act14', re.compile(r'акт\s*-?\s*14|акт14', re.I), 'Акт 14'),
)

NEW_BUILD = re.compile(
    r'(ново\s*строителство|новостроящ|ново-строителство|в\s*строеж|'
    r'новопостроен|ново\s*строителна|new\s*(?:build|construction)|'
    r'до\s*ключ|на\s*зелено|off[- ]plan)', re.I)

# A finished building being resold is not an off-plan risk and must not be
# filtered in with one.
RESALE = re.compile(r'(панелен|тухла\s*19|стар\s*фонд|preliminary\s*resale)', re.I)


def stage_of(text):
    """The construction milestone named in the text, or None."""
    if not text:
        return None, None
    for key, pattern, label in STAGES:
        if pattern.search(text):
            return key, label
    return None, None


def is_new_build(text):
    """New construction by any of the phrases agencies actually use."""
    if not text:
        return False
    if NEW_BUILD.search(text):
        return True
    key, _label = stage_of(text)
    # A building described by its Акт stage is under construction or just out
    # of it; a 1970s resale is never advertised that way.
    return key is not None


def describe(text):
    """(is_new_build, stage_key, stage_label) for one listing's text."""
    key, label = stage_of(text)
    return is_new_build(text), key, label
