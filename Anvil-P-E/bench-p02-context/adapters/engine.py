"""
Benchmark shim for: python run.py --adapter adapters.engine:Engine

The real engine lives at the repository root (adapters/engine.py). This module
loads it by file path so we do not circular-import bench-p02-context/adapters.engine.
"""
from __future__ import annotations

import importlib.util
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_BENCH = os.path.dirname(_HERE)
_REPO = os.path.dirname(os.path.dirname(_BENCH))

if _REPO not in sys.path:
    sys.path.insert(0, _REPO)
if _BENCH not in sys.path:
    sys.path.insert(0, _BENCH)

from adapter import Adapter  # noqa: E402


def _load_root_engine_class():
    path = os.path.join(_REPO, "adapters", "engine.py")
    spec = importlib.util.spec_from_file_location("_root_adapters_engine", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load root engine from {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.Engine


class Engine(_load_root_engine_class(), Adapter):
    """Root Mini Anvil engine, exposed under the bench adapters.engine namespace."""
