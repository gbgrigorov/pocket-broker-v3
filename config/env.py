# -*- coding: utf-8 -*-
"""Six-line .env reader. Deliberately not python-dotenv -- no new dependency.

Real environment variables always win, so production can set them properly and
`.env` stays a local-development convenience that is never committed.
"""
import os
from pathlib import Path

_LOADED = False


def load(path):
    global _LOADED
    if _LOADED or not Path(path).exists():
        return
    for line in Path(path).read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, _, value = line.partition('=')
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
    _LOADED = True


def get(key, default=None, cast=str):
    value = os.environ.get(key)
    if value is None or value == '':
        return default
    if cast is bool:
        return value.lower() in ('1', 'true', 'yes', 'on')
    return cast(value)
