# -*- coding: utf-8 -*-
"""Verbatim copies of the seaside-monitor crawler's parsing modules.

Nothing in this package may be edited casually. The files are byte-identical to
their upstream originals (see UPSTREAM.md for the manifest and checksums) so
that a fix made on either side stays diffable and the two projects can still be
merged later. tests/test_vendor_parity.py fails if that stops being true.

Upstream imports its siblings flatly -- `import vocab`, `from xlsx_reader import
read_workbook`. Rewriting those to relative imports would be the first edit and
would break byte-identity for no gain, so this package puts its own directory on
sys.path instead and lets the originals resolve exactly as they do upstream.
"""
import sys
from pathlib import Path

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from normalize import extract_offers, fingerprint, dup_group, weak_core, norm_text  # noqa: E402
from xlsx_reader import read_workbook                                              # noqa: E402
from parse_registry import main as parse_registry_main                             # noqa: E402
import vocab                                                                        # noqa: E402

__all__ = ['extract_offers', 'fingerprint', 'dup_group', 'weak_core', 'norm_text',
           'read_workbook', 'vocab', 'parse_registry_main']
