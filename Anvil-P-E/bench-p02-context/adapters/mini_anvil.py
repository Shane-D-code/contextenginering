"""
Mini Anvil — P-02 Persistent Context Engine
Benchmark adapter shim: wires the benchmark harness to our engine.

Run from bench-p02-context/:
    python self_check.py --adapter adapters.mini_anvil:Engine --quick
    python run.py --adapter adapters.mini_anvil:Engine --mode fast \\
        --seeds 9999 31415 27182 16180 11235 --out report.json
"""
from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_BENCH = os.path.dirname(_HERE)
_REPO = os.path.dirname(os.path.dirname(_BENCH))
for _p in (_REPO, _BENCH):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from adapter import Adapter  # noqa: E402
from adapters.engine import Engine as _RootEngine  # noqa: E402


class Engine(_RootEngine, Adapter):
    """Delegates ingest / reconstruct_context / close to the root engine."""
