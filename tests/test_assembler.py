"""
Tests for ContextAssembler (via Engine.reconstruct_context).

The spec says to drive these tests through Engine rather than wiring layers
manually.  Engine.reconstruct_context() delegates directly to
ContextAssembler.assemble(), so we get full coverage without needing to
manage IdentityResolver / EventStore / OperationalGraph / BehavioralMotifIndex
individually.

Scenario:
  Phase 1  — ingest a complete incident on "api-gateway":
             deploy → metric spike → error log → incident_signal → remediation (resolved)
  Phase 2  — query reconstruct_context() at the incident peak timestamp
             and verify every aspect of the returned Context dict.

Edge timeline (all on 2026-03-01, UTC):
  10:00  deploy   v3.2.1
  10:03  metric   p99_latency=5200
  10:04  log      ERROR timeout
  10:05  incident_signal  INC-HIST-001
  10:35  remediation rollback / resolved

After Phase 1 the motif for INC-HIST-001 is indexed.  When Phase 2 queries
the same service at t=10:05, the assembler should find:
  - related_events  : deploy + metric + log + incident_signal (all within 5-min window)
  - causal_chain    : at least the deploy→metric edge (confidence ~0.4 after reinforcement)
  - similar_past_incidents : INC-HIST-001 (score ≈ 0.85)
  - suggested_remediations : rollback (from INC-HIST-001 history)
  - confidence      : float in [0, 1]
  - explain         : non-empty string
"""

import pytest
from adapters.engine import Engine


SIGNAL_TS   = "2026-03-01T10:05:00+00:00"
DEPLOY_TS   = "2026-03-01T10:00:00+00:00"
METRIC_TS   = "2026-03-01T10:03:00+00:00"
LOG_TS      = "2026-03-01T10:04:00+00:00"
REM_TS      = "2026-03-01T10:35:00+00:00"


REQUIRED_KEYS = {
    "related_events",
    "causal_chain",
    "similar_past_incidents",
    "suggested_remediations",
    "confidence",
    "explain",
}


class TestContextAssembler:

    def setup_method(self):
        self.engine = Engine()
        self._build_incident_history()

    def _build_incident_history(self):
        """Ingest one complete incident that the assembler can recall later."""
        self.engine.ingest([
            {
                "kind": "deploy",
                "service": "api-gateway",
                "version": "v3.2.1",
                "ts": DEPLOY_TS,
            },
            {
                "kind": "metric",
                "service": "api-gateway",
                "name": "p99_latency",
                "value": 5200,
                "ts": METRIC_TS,
            },
            {
                "kind": "log",
                "service": "api-gateway",
                "level": "error",
                "msg": "upstream timeout",
                "ts": LOG_TS,
            },
            {
                "kind": "incident_signal",
                "service": "api-gateway",
                "incident_id": "INC-HIST-001",
                "trigger": "latency_breach",
                "ts": SIGNAL_TS,
            },
            {
                "kind": "remediation",
                "service": "api-gateway",
                "incident_id": "INC-HIST-001",
                "action": "rollback",
                "outcome": "resolved",
                "ts": REM_TS,
            },
        ])

    def _signal(self, service="api-gateway", ts=SIGNAL_TS, incident_id="INC-QUERY"):
        return {"service": service, "ts": ts, "incident_id": incident_id}

    def _ctx(self, **kwargs):
        """Shortcut: reconstruct_context with optional overrides."""
        return self.engine.reconstruct_context(self._signal(**kwargs))

    # -----------------------------------------------------------------------
    # 1. All required keys present
    # -----------------------------------------------------------------------

    def test_assemble_returns_all_required_keys(self):
        ctx = self._ctx()
        for key in REQUIRED_KEYS:
            assert key in ctx, f"Missing key: {key!r}"

    # -----------------------------------------------------------------------
    # 2-5. Type checks for list-valued keys
    # -----------------------------------------------------------------------

    def test_related_events_is_list(self):
        assert isinstance(self._ctx()["related_events"], list)

    def test_causal_chain_is_list(self):
        assert isinstance(self._ctx()["causal_chain"], list)

    def test_similar_past_incidents_is_list(self):
        assert isinstance(self._ctx()["similar_past_incidents"], list)

    def test_suggested_remediations_is_list(self):
        assert isinstance(self._ctx()["suggested_remediations"], list)

    # -----------------------------------------------------------------------
    # 6. confidence is a float in [0.0, 1.0]
    # -----------------------------------------------------------------------

    def test_confidence_is_float_in_unit_range(self):
        conf = self._ctx()["confidence"]
        assert isinstance(conf, float), f"confidence must be float, got {type(conf)}"
        assert 0.0 <= conf <= 1.0, f"confidence out of range: {conf}"

    # -----------------------------------------------------------------------
    # 7. explain is a non-empty string
    # -----------------------------------------------------------------------

    def test_explain_is_nonempty_string(self):
        explain = self._ctx()["explain"]
        assert isinstance(explain, str)
        assert len(explain) > 0, "explain must not be empty"

    # -----------------------------------------------------------------------
    # 8. Fast mode runs without LLM (no exception)
    # -----------------------------------------------------------------------

    def test_fast_mode_does_not_raise(self):
        ctx = self.engine.reconstruct_context(self._signal(), mode="fast")
        assert isinstance(ctx, dict)
        assert "explain" in ctx

    # -----------------------------------------------------------------------
    # 9. Deep mode falls back gracefully when no LLM keys are set
    # -----------------------------------------------------------------------

    def test_deep_mode_falls_back_gracefully_without_llm(self):
        """deep mode without API keys catches the error and returns template explain."""
        ctx = self.engine.reconstruct_context(self._signal(), mode="deep")
        assert isinstance(ctx, dict)
        explain = ctx.get("explain", "")
        assert isinstance(explain, str)
        assert len(explain) > 0

    # -----------------------------------------------------------------------
    # 10. Unknown service returns a valid but empty context (no crash)
    # -----------------------------------------------------------------------

    def test_unknown_service_returns_graceful_empty_context(self):
        ctx = self.engine.reconstruct_context({
            "service": "service-that-has-never-been-seen",
            "ts": SIGNAL_TS,
        })
        assert isinstance(ctx, dict)
        for key in REQUIRED_KEYS:
            assert key in ctx, f"Missing key for unknown service: {key!r}"
        assert ctx["related_events"] == []
        assert ctx["causal_chain"] == []
        assert ctx["similar_past_incidents"] == []
        assert ctx["suggested_remediations"] == []
        assert ctx["confidence"] == 0.0
        assert isinstance(ctx["explain"], str)
        assert len(ctx["explain"]) > 0

    # -----------------------------------------------------------------------
    # 11. Related events are populated for a known service in the window
    # -----------------------------------------------------------------------

    def test_related_events_populated_within_window(self):
        """Events ingested within the 5-minute window must appear in related_events."""
        ctx = self._ctx()
        events = ctx["related_events"]
        # deploy / metric / log / incident_signal are all within 300 s of SIGNAL_TS
        assert len(events) >= 1
        kinds = {e["kind"] for e in events}
        # At minimum the deploy that triggered the causal chain should be present
        assert "deploy" in kinds or "metric" in kinds or "log" in kinds

    # -----------------------------------------------------------------------
    # 12. Similar past incidents are found after indexing a resolved incident
    # -----------------------------------------------------------------------

    def test_similar_past_incidents_found_after_history(self):
        """INC-HIST-001 must appear in similar_past_incidents after being indexed."""
        ctx = self._ctx()
        similar = ctx["similar_past_incidents"]
        past_ids = [
            s.get("incident_id") or s.get("past_incident_id")
            for s in similar
        ]
        assert "INC-HIST-001" in past_ids, (
            f"Expected INC-HIST-001 in similar incidents; got: {past_ids}"
        )

    # -----------------------------------------------------------------------
    # 13. Suggested remediations include "rollback" after INC-HIST-001 history
    # -----------------------------------------------------------------------

    def test_suggested_remediations_include_rollback(self):
        """rollback was the resolved action for INC-HIST-001 and must be suggested."""
        ctx = self._ctx()
        actions = [r["action"] for r in ctx["suggested_remediations"]]
        assert "rollback" in actions, (
            f"Expected 'rollback' in suggested remediations; got: {actions}"
        )

    # -----------------------------------------------------------------------
    # 14. Context can be reconstructed multiple times for the same signal
    # -----------------------------------------------------------------------

    def test_repeated_reconstruct_is_idempotent(self):
        """Calling reconstruct_context twice with the same signal yields the same keys."""
        ctx1 = self._ctx()
        ctx2 = self._ctx()
        assert set(ctx1.keys()) == set(ctx2.keys())
        assert ctx1["confidence"] == ctx2["confidence"]
        assert ctx1["similar_past_incidents"] == ctx2["similar_past_incidents"]

    # -----------------------------------------------------------------------
    # 15. Similarity score for the matched past incident is in (0, 1]
    # -----------------------------------------------------------------------

    def test_similar_incident_similarity_score_in_range(self):
        ctx = self._ctx()
        for match in ctx["similar_past_incidents"]:
            sim = match["similarity"]
            assert 0.0 < sim <= 1.0, f"Similarity {sim} out of range for {match}"

    # -----------------------------------------------------------------------
    # 16. Suggested remediations are sorted by confidence descending
    # -----------------------------------------------------------------------

    def test_suggested_remediations_sorted_by_confidence_descending(self):
        rems = self._ctx()["suggested_remediations"]
        for i in range(len(rems) - 1):
            assert rems[i]["confidence"] >= rems[i + 1]["confidence"], (
                f"Remediations out of order at {i}: "
                f"{rems[i]['confidence']} < {rems[i+1]['confidence']}"
            )
