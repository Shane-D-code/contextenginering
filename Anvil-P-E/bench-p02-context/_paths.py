"""Ensure bench-p02-context and repository root are on sys.path."""
from __future__ import annotations

import os
import sys

_BENCH = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(os.path.dirname(_BENCH))

for _p in (_REPO, _BENCH):
    if _p not in sys.path:
        sys.path.insert(0, _p)
