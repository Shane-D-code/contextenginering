"""
Shared pytest fixtures for Mini Anvil test suite.
"""
from __future__ import annotations

import pytest
import tempfile
import os
import sys

# Ensure project root is on the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from adapters.engine import Engine
from engine.identity import IdentityResolver
from engine.store import EventStore
from engine.graph import OperationalGraph
from engine.motifs import BehavioralMotifIndex
from engine.assembler import ContextAssembler


@pytest.fixture
def engine():
    """Fresh Engine instance per test."""
    e = Engine()
    yield e
    try:
        e.close()
    except Exception:
        pass


@pytest.fixture
def resolver():
    return IdentityResolver()


@pytest.fixture
def graph():
    return OperationalGraph()


@pytest.fixture
def motif_index():
    return BehavioralMotifIndex()


@pytest.fixture
def event_store():
    store = EventStore(":memory:")
    yield store
    store.close()


@pytest.fixture
def assembler():
    return ContextAssembler()


@pytest.fixture
def sample_events():
    """Complete incident lifecycle events."""
    return [
        {"kind": "deploy", "service": "test-svc", "version": "v1.0.0", "ts": "2026-01-15T10:00:00+00:00"},
        {"kind": "metric", "service": "test-svc", "name": "latency", "value": 500, "ts": "2026-01-15T10:05:00+00:00"},
        {"kind": "log", "service": "test-svc", "level": "error", "msg": "timeout", "trace_id": "tr-abc", "ts": "2026-01-15T10:06:00+00:00"},
        {"kind": "incident_signal", "service": "test-svc", "incident_id": "INC-SAMPLE", "trigger": "latency", "ts": "2026-01-15T10:07:00+00:00"},
        {"kind": "log", "service": "test-svc", "level": "error", "msg": "retry failed", "ts": "2026-01-15T10:08:00+00:00"},
        {"kind": "remediation", "service": "test-svc", "incident_id": "INC-SAMPLE", "action": "rollback", "outcome": "resolved", "ts": "2026-01-15T10:37:00+00:00"},
    ]
