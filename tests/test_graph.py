"""
Tests for Layer 3: OperationalGraph (engine/graph.py)

Covers:
- add_edge() — initial confidence/count, temporal enforcement, reinforcement, cap
- get_edge() — happy path, missing edge, wrong relation filter
- get_causal_chain() — forward/backward BFS, max_hops, min_confidence,
                       unknown CID, sort order
- reinforce_remediation() — "resolved" boosts confidence, other outcomes are no-ops
- apply_decay_node() — reduces confidence per day, floors at 0.1
- apply_decay_all() — decays every edge, floors at 0.1
- record_deploy() + get_recent_deploy() — within/outside window
- extract_motif() — abstract shape contains no canonical IDs
- get_stats() — returns correct keys and counts

All timestamps use ISO-8601 with +00:00 timezone offset.
"""

import pytest

from engine.graph import OperationalGraph
from engine.models import CausalEdge, IncidentMotif


class TestOperationalGraph:
    # ------------------------------------------------------------------ #
    # Fixed timestamps (monotonically increasing by 1 minute)             #
    # ------------------------------------------------------------------ #

    T1 = "2024-01-01T10:00:00+00:00"
    T2 = "2024-01-01T10:01:00+00:00"
    T3 = "2024-01-01T10:02:00+00:00"
    T4 = "2024-01-01T10:03:00+00:00"
    T5 = "2024-01-01T10:04:00+00:00"
    T6 = "2024-01-01T10:05:00+00:00"

    # Timestamps for decay tests: last_seen at T2, decay applied 10 days later
    T2_PLUS_10D = "2024-01-11T10:01:00+00:00"
    FAR_FUTURE  = "2025-06-01T10:00:00+00:00"  # hundreds of days later

    # ------------------------------------------------------------------ #
    # Setup                                                                #
    # ------------------------------------------------------------------ #

    def setup_method(self):
        self.g = OperationalGraph()

    # ================================================================== #
    # add_edge()                                                          #
    # ================================================================== #

    def test_add_edge_creates_edge_with_initial_confidence(self):
        self.g.add_edge("A", "B", "calls", "e1", self.T1, self.T2)
        edge = self.g.get_edge("A", "B")
        assert edge is not None
        assert edge.confidence == pytest.approx(0.3)

    def test_add_edge_creates_edge_with_initial_count(self):
        self.g.add_edge("A", "B", "calls", "e1", self.T1, self.T2)
        edge = self.g.get_edge("A", "B")
        assert edge.count == 1

    def test_add_edge_stores_relation_first_and_last_seen(self):
        self.g.add_edge("A", "B", "calls", "e1", self.T1, self.T2)
        edge = self.g.get_edge("A", "B")
        assert edge.relation == "calls"
        assert edge.first_seen == self.T1
        assert edge.last_seen == self.T2

    def test_add_edge_stores_evidence_id(self):
        self.g.add_edge("A", "B", "calls", "evidence-99", self.T1, self.T2)
        edge = self.g.get_edge("A", "B")
        assert "evidence-99" in edge.evidence_ids

    def test_add_edge_temporal_violation_drops_edge_when_src_after_dst(self):
        # ts_src > ts_dst → strictly violates ordering → edge NOT created
        self.g.add_edge("A", "B", "calls", "e1", self.T2, self.T1)
        assert self.g.get_edge("A", "B") is None

    def test_add_edge_temporal_violation_drops_edge_when_equal(self):
        # ts_src == ts_dst → not strictly before → edge NOT created
        self.g.add_edge("A", "B", "calls", "e1", self.T1, self.T1)
        assert self.g.get_edge("A", "B") is None

    def test_add_edge_reinforces_existing_edge_increments_count(self):
        self.g.add_edge("A", "B", "calls", "e1", self.T1, self.T2)
        self.g.add_edge("A", "B", "calls", "e2", self.T2, self.T3)
        edge = self.g.get_edge("A", "B")
        assert edge.count == 2

    def test_add_edge_reinforces_existing_edge_increases_confidence(self):
        self.g.add_edge("A", "B", "calls", "e1", self.T1, self.T2)
        self.g.add_edge("A", "B", "calls", "e2", self.T2, self.T3)
        edge = self.g.get_edge("A", "B")
        # 0.3 + 0.05 = 0.35
        assert edge.confidence == pytest.approx(0.35, abs=1e-9)

    def test_add_edge_confidence_capped_at_0_95(self):
        # Initial: 0.3.  Each reinforce: +0.05.
        # After 13 reinforcements: 0.3 + 13×0.05 = 0.95; further calls stay at 0.95.
        for i in range(20):
            self.g.add_edge("A", "B", "calls", f"e{i}", self.T1, self.T2)
        edge = self.g.get_edge("A", "B")
        assert edge.confidence == pytest.approx(0.95, abs=1e-9)

    def test_add_edge_updates_last_seen_on_reinforce(self):
        self.g.add_edge("A", "B", "calls", "e1", self.T1, self.T2)
        self.g.add_edge("A", "B", "calls", "e2", self.T3, self.T4)
        edge = self.g.get_edge("A", "B")
        assert edge.last_seen == self.T4  # updated to newest ts_dst

    # ================================================================== #
    # get_edge()                                                           #
    # ================================================================== #

    def test_get_edge_returns_causal_edge_instance(self):
        self.g.add_edge("A", "B", "deploy", "e1", self.T1, self.T2)
        edge = self.g.get_edge("A", "B")
        assert isinstance(edge, CausalEdge)

    def test_get_edge_returns_none_for_missing_edge(self):
        assert self.g.get_edge("X", "Y") is None

    def test_get_edge_returns_none_for_wrong_relation_filter(self):
        self.g.add_edge("A", "B", "calls", "e1", self.T1, self.T2)
        # Stored relation is "calls"; querying for "deploy" should return None
        assert self.g.get_edge("A", "B", relation="deploy") is None

    def test_get_edge_returns_edge_with_matching_relation_filter(self):
        self.g.add_edge("A", "B", "calls", "e1", self.T1, self.T2)
        edge = self.g.get_edge("A", "B", relation="calls")
        assert edge is not None
        assert edge.relation == "calls"

    # ================================================================== #
    # get_causal_chain()                                                   #
    # ================================================================== #

    def test_get_causal_chain_includes_outgoing_edges(self):
        self.g.add_edge("SRC", "MID", "calls", "e1", self.T1, self.T2)
        chain = self.g.get_causal_chain("SRC")
        pairs = {(e.src_cid, e.dst_cid) for e in chain}
        assert ("SRC", "MID") in pairs

    def test_get_causal_chain_includes_incoming_edges(self):
        # Start search from MID; the predecessor edge SRC→MID should appear
        self.g.add_edge("SRC", "MID", "calls", "e1", self.T1, self.T2)
        chain = self.g.get_causal_chain("MID")
        pairs = {(e.src_cid, e.dst_cid) for e in chain}
        assert ("SRC", "MID") in pairs

    def test_get_causal_chain_unknown_cid_returns_empty_list(self):
        # Must not crash; an unknown node produces an empty chain
        chain = self.g.get_causal_chain("ghost-service")
        assert chain == []

    def test_get_causal_chain_respects_max_hops(self):
        # Chain: A → B → C → D
        # With max_hops=1, BFS from A processes depths 0 (A) and 1 (B).
        # C→D is added only when processing C at depth 2, which is skipped.
        self.g.add_edge("A", "B", "calls", "e1", self.T1, self.T2)
        self.g.add_edge("B", "C", "calls", "e2", self.T2, self.T3)
        self.g.add_edge("C", "D", "calls", "e3", self.T3, self.T4)
        chain = self.g.get_causal_chain("A", max_hops=1)
        pairs = {(e.src_cid, e.dst_cid) for e in chain}
        # C→D must NOT appear
        assert ("C", "D") not in pairs
        # A→B must appear
        assert ("A", "B") in pairs

    def test_get_causal_chain_respects_min_confidence(self):
        # Default confidence is 0.3; filtering at 0.4 should yield nothing
        self.g.add_edge("A", "B", "calls", "e1", self.T1, self.T2)
        chain = self.g.get_causal_chain("A", min_confidence=0.4)
        assert chain == []

    def test_get_causal_chain_includes_edges_above_min_confidence(self):
        # Reinforce once → confidence 0.35; min_confidence=0.35 should include it
        self.g.add_edge("A", "B", "calls", "e1", self.T1, self.T2)
        self.g.add_edge("A", "B", "calls", "e2", self.T2, self.T3)
        chain = self.g.get_causal_chain("A", min_confidence=0.35)
        pairs = {(e.src_cid, e.dst_cid) for e in chain}
        assert ("A", "B") in pairs

    def test_get_causal_chain_sorted_oldest_first(self):
        # Edge A→B has first_seen=T1; edge B→C has first_seen=T3.
        # Entire chain (including duplicates from BFS) must be sorted ascending.
        self.g.add_edge("A", "B", "calls", "e1", self.T1, self.T2)
        self.g.add_edge("B", "C", "calls", "e2", self.T3, self.T4)
        chain = self.g.get_causal_chain("B")
        assert len(chain) >= 2
        first_seens = [e.first_seen for e in chain]
        assert first_seens == sorted(first_seens), "Chain is not sorted oldest-first"
        # A→B (first_seen=T1) must appear before B→C (first_seen=T3)
        pairs = [(e.src_cid, e.dst_cid) for e in chain]
        ab_min = min(i for i, p in enumerate(pairs) if p == ("A", "B"))
        bc_min = min(i for i, p in enumerate(pairs) if p == ("B", "C"))
        assert ab_min < bc_min

    # ================================================================== #
    # reinforce_remediation()                                              #
    # ================================================================== #

    def test_reinforce_remediation_boosts_confidence_on_resolved(self):
        # Edge A→B; last_seen=T2.  Reinforce at T2+9min (within 600 s window).
        self.g.add_edge("A", "B", "calls", "e1", self.T1, self.T2)
        reinforce_ts = "2024-01-01T10:10:00+00:00"  # 9 min after T2
        self.g.reinforce_remediation("A", "inc-001", "rollback", "resolved", reinforce_ts, window_s=600)
        edge = self.g.get_edge("A", "B")
        # 0.3 + 0.10 = 0.40
        assert edge.confidence == pytest.approx(0.40, abs=1e-9)

    def test_reinforce_remediation_sets_remediation_reinforced_flag(self):
        self.g.add_edge("A", "B", "calls", "e1", self.T1, self.T2)
        reinforce_ts = "2024-01-01T10:10:00+00:00"
        self.g.reinforce_remediation("A", "inc-001", "rollback", "resolved", reinforce_ts, window_s=600)
        edge = self.g.get_edge("A", "B")
        assert edge.remediation_reinforced is True

    def test_reinforce_remediation_caps_confidence_at_0_95(self):
        # Boost starting confidence close to cap via multiple reinforcements
        for i in range(14):  # 0.3 + 14×0.05 → 1.0 clamped to 0.95
            self.g.add_edge("A", "B", "calls", f"e{i}", self.T1, self.T2)
        reinforce_ts = "2024-01-01T10:10:00+00:00"
        self.g.reinforce_remediation("A", "inc-cap", "restart", "resolved", reinforce_ts, window_s=600)
        edge = self.g.get_edge("A", "B")
        assert edge.confidence <= 0.95 + 1e-9

    def test_reinforce_remediation_no_effect_for_failed_outcome(self):
        self.g.add_edge("A", "B", "calls", "e1", self.T1, self.T2)
        reinforce_ts = "2024-01-01T10:10:00+00:00"
        self.g.reinforce_remediation("A", "inc-001", "rollback", "failed", reinforce_ts)
        edge = self.g.get_edge("A", "B")
        assert edge.confidence == pytest.approx(0.3)
        assert edge.remediation_reinforced is False

    def test_reinforce_remediation_no_effect_for_investigating_outcome(self):
        self.g.add_edge("A", "B", "calls", "e1", self.T1, self.T2)
        reinforce_ts = "2024-01-01T10:10:00+00:00"
        self.g.reinforce_remediation("A", "inc-002", "restart", "investigating", reinforce_ts)
        edge = self.g.get_edge("A", "B")
        assert edge.confidence == pytest.approx(0.3)

    def test_reinforce_remediation_records_remediation_history(self):
        self.g.add_edge("A", "B", "calls", "e1", self.T1, self.T2)
        reinforce_ts = "2024-01-01T10:10:00+00:00"
        self.g.reinforce_remediation("A", "inc-001", "rollback", "resolved", reinforce_ts)
        history = self.g.get_remediation_history("A")
        assert len(history) == 1
        assert history[0]["incident_id"] == "inc-001"
        assert history[0]["outcome"] == "resolved"

    # ================================================================== #
    # apply_decay_node()                                                   #
    # ================================================================== #

    def test_apply_decay_node_reduces_confidence(self):
        # Edge A→B; last_seen=T2.  Decay 10 days later → -0.01×10 = -0.10
        self.g.add_edge("A", "B", "calls", "e1", self.T1, self.T2)
        self.g.apply_decay_node("A", self.T2_PLUS_10D)
        edge = self.g.get_edge("A", "B")
        # max(0.1, 0.3 - 0.1) = 0.2
        assert edge.confidence == pytest.approx(0.2, abs=0.01)

    def test_apply_decay_node_returns_decayed_count(self):
        self.g.add_edge("A", "B", "calls", "e1", self.T1, self.T2)
        count = self.g.apply_decay_node("A", self.T2_PLUS_10D)
        assert count == 1

    def test_apply_decay_node_floor_at_0_1(self):
        # Hundreds of days of decay must not push confidence below 0.1
        self.g.add_edge("A", "B", "calls", "e1", self.T1, self.T2)
        self.g.apply_decay_node("A", self.FAR_FUTURE)
        edge = self.g.get_edge("A", "B")
        assert edge.confidence == pytest.approx(0.1, abs=1e-9)

    def test_apply_decay_node_zero_days_no_change(self):
        # Decaying at the same instant as last_seen → days_old = 0 → no change
        self.g.add_edge("A", "B", "calls", "e1", self.T1, self.T2)
        count = self.g.apply_decay_node("A", self.T2)
        assert count == 0
        edge = self.g.get_edge("A", "B")
        assert edge.confidence == pytest.approx(0.3)

    # ================================================================== #
    # apply_decay_all()                                                    #
    # ================================================================== #

    def test_apply_decay_all_decays_all_edges(self):
        # Two edges from different sources
        self.g.add_edge("X", "Y", "calls", "e1", self.T1, self.T2)
        self.g.add_edge("P", "Q", "calls", "e2", self.T1, self.T2)
        decayed = self.g.apply_decay_all(self.FAR_FUTURE)
        assert decayed == 2

    def test_apply_decay_all_floor_at_0_1(self):
        self.g.add_edge("X", "Y", "calls", "e1", self.T1, self.T2)
        self.g.apply_decay_all(self.FAR_FUTURE)
        edge = self.g.get_edge("X", "Y")
        assert edge.confidence == pytest.approx(0.1, abs=1e-9)

    def test_apply_decay_all_returns_zero_for_zero_days(self):
        # Decaying at the same time as last_seen → days_old = 0 → nothing changes
        self.g.add_edge("X", "Y", "calls", "e1", self.T1, self.T2)
        count = self.g.apply_decay_all(self.T2)
        assert count == 0

    # ================================================================== #
    # record_deploy() + get_recent_deploy()                               #
    # ================================================================== #

    def test_record_deploy_and_get_recent_deploy_within_window(self):
        deploy_ts = "2024-01-01T09:55:00+00:00"  # 5 min before anchor
        anchor_ts = "2024-01-01T10:00:00+00:00"
        self.g.record_deploy("svc-a", "v1.2.3", deploy_ts)
        result = self.g.get_recent_deploy("svc-a", anchor_ts, window_s=600)
        assert result is not None
        assert result["version"] == "v1.2.3"

    def test_get_recent_deploy_returns_most_recent_within_window(self):
        anchor_ts  = "2024-01-01T10:00:00+00:00"
        older_ts   = "2024-01-01T09:51:00+00:00"
        newer_ts   = "2024-01-01T09:55:00+00:00"
        self.g.record_deploy("svc-a", "v1.0.0", older_ts)
        self.g.record_deploy("svc-a", "v2.0.0", newer_ts)
        result = self.g.get_recent_deploy("svc-a", anchor_ts, window_s=600)
        assert result["version"] == "v2.0.0"

    def test_get_recent_deploy_returns_none_when_outside_window(self):
        # Deploy 15 minutes before anchor; 600 s window covers only 10 minutes
        old_ts    = "2024-01-01T09:45:00+00:00"
        anchor_ts = "2024-01-01T10:00:00+00:00"
        self.g.record_deploy("svc-a", "v1.0.0", old_ts)
        assert self.g.get_recent_deploy("svc-a", anchor_ts, window_s=600) is None

    def test_get_recent_deploy_returns_none_when_no_deploys(self):
        assert self.g.get_recent_deploy("svc-nobody", self.T1, window_s=600) is None

    # ================================================================== #
    # extract_motif()                                                      #
    # ================================================================== #

    def test_extract_motif_returns_incident_motif_instance(self):
        self.g.add_edge("abc12345", "def67890", "calls", "e1", self.T1, self.T2)
        edge = self.g.get_edge("abc12345", "def67890")
        motif = self.g.extract_motif([edge])
        assert isinstance(motif, IncidentMotif)

    def test_extract_motif_causal_shape_contains_no_canonical_ids(self):
        src_cid = "abc12345"
        dst_cid = "def67890"
        self.g.add_edge(src_cid, dst_cid, "calls", "e1", self.T1, self.T2)
        edge = self.g.get_edge(src_cid, dst_cid)
        motif = self.g.extract_motif([edge])
        shape_str = str(motif.causal_shape)
        assert src_cid not in shape_str, "src canonical_id leaked into causal_shape"
        assert dst_cid not in shape_str, "dst canonical_id leaked into causal_shape"

    def test_extract_motif_event_sequence_derived_from_relations(self):
        # "deploy" → role DEPLOY;  "error_log" → role ERROR_LOG
        self.g.add_edge("A", "B", "deploy",    "e1", self.T1, self.T2)
        self.g.add_edge("B", "C", "error_log", "e2", self.T3, self.T4)
        edge1 = self.g.get_edge("A", "B")
        edge2 = self.g.get_edge("B", "C")
        motif = self.g.extract_motif([edge1, edge2])
        assert "DEPLOY" in motif.event_sequence
        assert "ERROR_LOG" in motif.event_sequence

    def test_extract_motif_empty_edges_returns_zero_confidence(self):
        motif = self.g.extract_motif([])
        assert motif.confidence == 0.0

    def test_extract_motif_confidence_is_average_of_edge_confidences(self):
        self.g.add_edge("A", "B", "calls", "e1", self.T1, self.T2)
        edge = self.g.get_edge("A", "B")
        motif = self.g.extract_motif([edge])
        # Single edge at confidence 0.3 → average = 0.3
        assert motif.confidence == pytest.approx(0.3, abs=1e-9)

    # ================================================================== #
    # get_stats()                                                          #
    # ================================================================== #

    def test_get_stats_returns_all_required_keys(self):
        stats = self.g.get_stats()
        assert "num_nodes"        in stats
        assert "num_edges"        in stats
        assert "num_deploys"      in stats
        assert "num_remediations" in stats
        assert "avg_confidence"   in stats

    def test_get_stats_empty_graph(self):
        stats = self.g.get_stats()
        assert stats["num_nodes"]   == 0
        assert stats["num_edges"]   == 0
        assert stats["num_deploys"] == 0

    def test_get_stats_counts_correctly(self):
        # 2 edges → 3 nodes (X, Y, Z); 2 deploys; 0 remediations
        self.g.add_edge("X", "Y", "calls", "e1", self.T1, self.T2)
        self.g.add_edge("Y", "Z", "calls", "e2", self.T2, self.T3)
        self.g.record_deploy("X", "v1.0", self.T1)
        self.g.record_deploy("X", "v2.0", self.T2)
        stats = self.g.get_stats()
        assert stats["num_nodes"]   == 3
        assert stats["num_edges"]   == 2
        assert stats["num_deploys"] == 2
        assert stats["avg_confidence"] == pytest.approx(0.3, abs=1e-9)

    def test_get_stats_num_remediations_increments(self):
        self.g.add_edge("A", "B", "calls", "e1", self.T1, self.T2)
        reinforce_ts = "2024-01-01T10:10:00+00:00"
        self.g.reinforce_remediation("A", "inc-1", "rollback", "resolved", reinforce_ts)
        stats = self.g.get_stats()
        assert stats["num_remediations"] == 1
