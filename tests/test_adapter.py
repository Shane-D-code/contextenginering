"""
Tests for the Engine adapter (adapters/engine.py).

Covers every public entry-point: ingest(), reconstruct_context(), close().
Validates that each event kind is routed correctly and that topology mutations
(renames) propagate into the IdentityResolver.

All timestamps use a fixed BASE_TIME to keep tests deterministic and to avoid
confidence-decay surprises (all events are on the same day, so days_old == 0).
"""

import pytest
from datetime import datetime, timedelta, timezone

from adapters.engine import Engine


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

BASE_TIME = datetime(2026, 5, 1, 9, 0, 0, tzinfo=timezone.utc)

REQUIRED_CONTEXT_KEYS = {
    "related_events",
    "causal_chain",
    "similar_past_incidents",
    "suggested_remediations",
    "confidence",
    "explain",
}


def ts(delta_min: float = 0) -> str:
    """Return an ISO-8601 UTC timestamp offset by delta_min from BASE_TIME."""
    return (BASE_TIME + timedelta(minutes=delta_min)).isoformat()


def make_incident(service: str, inc_id: str, offset_min: float = 0) -> list:
    """
    Create a minimal but complete incident event sequence:
      deploy → metric → log → incident_signal → remediation (resolved)

    All events carry a 'service' field and are separated by a few minutes so
    causal edges are formed (metric follows deploy within 600 s window).
    """
    return [
        {
            "kind": "deploy",
            "service": service,
            "version": "v1.0.0",
            "ts": ts(offset_min + 0),
        },
        {
            "kind": "metric",
            "service": service,
            "name": "cpu_pct",
            "value": 92,
            "ts": ts(offset_min + 3),
        },
        {
            "kind": "log",
            "service": service,
            "level": "error",
            "msg": "out of memory",
            "ts": ts(offset_min + 4),
        },
        {
            "kind": "incident_signal",
            "service": service,
            "incident_id": inc_id,
            "trigger": "cpu_breach",
            "ts": ts(offset_min + 5),
        },
        {
            "kind": "remediation",
            "service": service,
            "incident_id": inc_id,
            "action": "rollback",
            "outcome": "resolved",
            "ts": ts(offset_min + 35),
        },
    ]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestEngine:

    def setup_method(self):
        """Fresh Engine for every test — no shared state."""
        self.engine = Engine()

    # -----------------------------------------------------------------------
    # 1. Initial state
    # -----------------------------------------------------------------------

    def test_initial_state_is_empty(self):
        """A freshly constructed Engine has empty stores."""
        assert self.engine.motifs.count() == 0
        assert self.engine.store.count() == 0

    # -----------------------------------------------------------------------
    # 2. Deploy event recorded in graph
    # -----------------------------------------------------------------------

    def test_ingest_deploy_records_in_graph(self):
        """A deploy event must be tracked by OperationalGraph.get_recent_deploy()."""
        self.engine.ingest([{
            "kind": "deploy",
            "service": "svc-deploy-test",
            "version": "v2.0.0",
            "ts": ts(0),
        }])
        cid = self.engine.resolver.resolve("svc-deploy-test")
        deploy = self.engine.graph.get_recent_deploy(cid, ts(5), window_s=600)

        assert deploy is not None, "deploy not recorded in graph"
        assert deploy["version"] == "v2.0.0"

    # -----------------------------------------------------------------------
    # 3. Rename topology event maps both names to the same canonical_id
    # -----------------------------------------------------------------------

    def test_ingest_rename_maps_both_names_to_same_cid(self):
        """After a rename event, old and new service names resolve to the same CID."""
        self.engine.ingest([
            {"kind": "deploy", "service": "svc-old", "version": "v1", "ts": ts(0)},
            {
                "kind": "topology",
                "service": "svc-old",
                "ts": ts(10),
                "mutation": {
                    "kind": "rename",
                    "old_name": "svc-old",
                    "new_name": "svc-new",
                },
            },
        ])
        old_cid = self.engine.resolver.resolve("svc-old")
        new_cid = self.engine.resolver.resolve("svc-new")
        assert old_cid == new_cid, (
            f"Rename did not unify CIDs: old={old_cid}, new={new_cid}"
        )

    # -----------------------------------------------------------------------
    # 4. Remediation with outcome=resolved indexes a motif
    # -----------------------------------------------------------------------

    def test_ingest_remediation_resolved_indexes_motif(self):
        """A resolved remediation event must add exactly one motif to the index."""
        self.engine.ingest(make_incident("svc-rem", "INC-REM-001"))
        assert self.engine.motifs.count() == 1

    # -----------------------------------------------------------------------
    # 5. Remediation with outcome != resolved does NOT index a motif
    # -----------------------------------------------------------------------

    def test_ingest_remediation_unresolved_does_not_index_motif(self):
        """A failed remediation must not add any motif to the index."""
        self.engine.ingest([
            {"kind": "deploy", "service": "svc-fail", "version": "v1", "ts": ts(0)},
            {
                "kind": "incident_signal",
                "service": "svc-fail",
                "incident_id": "INC-FAIL-001",
                "trigger": "cpu",
                "ts": ts(5),
            },
            {
                "kind": "remediation",
                "service": "svc-fail",
                "incident_id": "INC-FAIL-001",
                "action": "rollback",
                "outcome": "failed",       # not resolved
                "ts": ts(10),
            },
        ])
        assert self.engine.motifs.count() == 0

    # -----------------------------------------------------------------------
    # 6. reconstruct_context returns all required keys
    # -----------------------------------------------------------------------

    def test_reconstruct_context_returns_required_keys(self):
        """Context dict must always contain the six canonical keys."""
        self.engine.ingest(make_incident("svc-ctx", "INC-CTX-001"))
        ctx = self.engine.reconstruct_context({
            "service": "svc-ctx",
            "ts": ts(5),
            "incident_id": "INC-CTX-001",
        })
        for key in REQUIRED_CONTEXT_KEYS:
            assert key in ctx, f"Missing key in context: {key!r}"

    # -----------------------------------------------------------------------
    # 7. reconstruct_context with an unknown service does not crash
    # -----------------------------------------------------------------------

    def test_reconstruct_context_unknown_service_no_crash(self):
        """Querying an unseen service must return a valid, mostly-empty context."""
        ctx = self.engine.reconstruct_context({
            "service": "never-heard-of-this-service",
            "ts": ts(0),
        })
        assert isinstance(ctx, dict)
        assert "confidence" in ctx
        assert ctx["related_events"] == []
        assert ctx["causal_chain"] == []
        assert ctx["confidence"] == 0.0

    # -----------------------------------------------------------------------
    # 8. Batch ingest of mixed event kinds does not raise
    # -----------------------------------------------------------------------

    def test_ingest_batch_of_mixed_kinds_no_error(self):
        """All six event kinds must be accepted and stored without exception."""
        events = [
            {"kind": "deploy",   "service": "svc-batch", "version": "v1",  "ts": ts(0)},
            {"kind": "metric",   "service": "svc-batch", "name": "cpu", "value": 50, "ts": ts(1)},
            {"kind": "log",      "service": "svc-batch", "level": "info", "msg": "ok", "ts": ts(2)},
            {"kind": "trace",    "service": "svc-batch", "trace_id": "tr-001", "spans": [], "ts": ts(3)},
            {"kind": "incident_signal", "service": "svc-batch", "incident_id": "INC-BATCH", "trigger": "manual", "ts": ts(4)},
            {"kind": "remediation",     "service": "svc-batch", "incident_id": "INC-BATCH",
             "action": "restart", "outcome": "resolved", "ts": ts(40)},
        ]
        self.engine.ingest(events)   # Must not raise
        assert self.engine.store.count() > 0

    # -----------------------------------------------------------------------
    # 9. close() can be called without error
    # -----------------------------------------------------------------------

    def test_close_no_error(self):
        """Engine.close() must be safe to call at any time."""
        engine = Engine()
        engine.ingest([{
            "kind": "deploy",
            "service": "svc-close",
            "version": "v1",
            "ts": ts(0),
        }])
        engine.close()   # Must not raise

    # -----------------------------------------------------------------------
    # 10. Two engines fed identical events produce identical confidence
    # -----------------------------------------------------------------------

    def test_two_engines_same_events_same_confidence(self):
        """Ingesting the same event stream into two separate Engines is deterministic."""
        events = make_incident("svc-clone", "INC-CLONE")
        signal = {"service": "svc-clone", "ts": ts(5), "incident_id": "INC-CLONE"}

        e1 = Engine()
        e1.ingest(events)
        ctx1 = e1.reconstruct_context(signal, mode="fast")

        e2 = Engine()
        e2.ingest(events)
        ctx2 = e2.reconstruct_context(signal, mode="fast")

        assert ctx1["confidence"] == ctx2["confidence"], (
            f"Confidence mismatch: {ctx1['confidence']} != {ctx2['confidence']}"
        )

    # -----------------------------------------------------------------------
    # 11. Events are persisted in the EventStore after ingest
    # -----------------------------------------------------------------------

    def test_events_stored_in_event_store_after_ingest(self):
        """Every non-topology event ingested must increase the EventStore count."""
        before = self.engine.store.count()
        self.engine.ingest([
            {"kind": "deploy", "service": "svc-count", "version": "v1", "ts": ts(0)},
            {"kind": "metric", "service": "svc-count", "name": "cpu",  "value": 50, "ts": ts(1)},
            {"kind": "log",    "service": "svc-count", "level": "info", "msg": "ok", "ts": ts(2)},
        ])
        assert self.engine.store.count() >= before + 3

    # -----------------------------------------------------------------------
    # 12. reconstruct_context returns correctly typed values
    # -----------------------------------------------------------------------

    def test_reconstruct_context_value_types(self):
        """All six context fields must have the correct Python types."""
        self.engine.ingest(make_incident("svc-types", "INC-TYPES"))
        ctx = self.engine.reconstruct_context({
            "service": "svc-types",
            "ts": ts(5),
        })
        assert isinstance(ctx["related_events"],         list)
        assert isinstance(ctx["causal_chain"],            list)
        assert isinstance(ctx["similar_past_incidents"],  list)
        assert isinstance(ctx["suggested_remediations"],  list)
        assert isinstance(ctx["confidence"],              float)
        assert isinstance(ctx["explain"],                 str)

    # -----------------------------------------------------------------------
    # 13. Topology event is stored in the EventStore
    # -----------------------------------------------------------------------

    def test_topology_event_stored_in_event_store(self):
        """Topology (rename) events must be persisted as kind='topology'."""
        before = self.engine.store.count()
        self.engine.ingest([{
            "kind": "topology",
            "service": "svc-top",
            "ts": ts(0),
            "mutation": {
                "kind": "rename",
                "old_name": "svc-top",
                "new_name": "svc-top-v2",
            },
        }])
        assert self.engine.store.count() > before

    # -----------------------------------------------------------------------
    # 14. Multiple incidents from the same service accumulate motifs
    # -----------------------------------------------------------------------

    def test_multiple_incidents_accumulate_motifs(self):
        """Each resolved incident adds a motif; count must match resolved incidents."""
        self.engine.ingest(make_incident("svc-multi", "INC-MULTI-001", offset_min=0))
        self.engine.ingest(make_incident("svc-multi", "INC-MULTI-002", offset_min=60))
        # Each resolved remediation indexes one motif
        assert self.engine.motifs.count() >= 2

    # -----------------------------------------------------------------------
    # 15. Context for known service has non-empty explain after history
    # -----------------------------------------------------------------------

    def test_reconstruct_context_explain_nonempty(self):
        """After ingesting a complete incident the explain field must be non-empty."""
        self.engine.ingest(make_incident("svc-explain", "INC-EXPL"))
        ctx = self.engine.reconstruct_context({
            "service": "svc-explain",
            "ts": ts(5),
        })
        assert isinstance(ctx["explain"], str)
        assert len(ctx["explain"]) > 0
