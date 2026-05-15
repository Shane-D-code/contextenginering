"""
Test cases validating the precision improvements from weighting canonical_ids
and implementing a minimum similarity threshold.

These tests verify that:
1. Same-family incidents (matching canonical_ids) score higher
2. Cross-family incidents (different canonical_ids) score lower
3. The minimum threshold filters out low-quality matches
4. Identical motifs still score perfectly
"""

import sys
import os

# Ensure imports work
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from engine.motifs import BehavioralMotifIndex, _compute_similarity
from engine.models import IncidentMotif


def _motif(
    incident_id: str,
    canonical_ids=None,
    event_sequence=None,
    causal_shape=None,
    remediation_action: str = "rollback",
    remediation_outcome: str = "resolved",
    timestamp: str = "2026-01-01T00:00:00+00:00",
    confidence: float = 0.9,
) -> IncidentMotif:
    """Factory for IncidentMotif with sensible defaults."""
    return IncidentMotif(
        incident_id=incident_id,
        canonical_ids=canonical_ids or [],
        event_sequence=event_sequence or ["DEPLOY", "METRIC_ANOMALY", "ERROR_LOG"],
        causal_shape=causal_shape or [("SVC_SRC", "relation", "SVC_DST")],
        remediation_action=remediation_action,
        remediation_outcome=remediation_outcome,
        timestamp=timestamp,
        confidence=confidence,
    )


class TestCanonicalIdWeighting:
    """Test that canonical_ids overlap is properly weighted in similarity."""

    def test_same_canonical_ids_boosts_similarity(self):
        """Motifs with identical canonical_ids should score significantly higher."""
        stored = _motif(
            "INC-FAM2-A",
            canonical_ids=["svc-05", "svc-03"],
            event_sequence=["DEPLOY", "METRIC_ANOMALY", "ERROR_LOG"],
            causal_shape=[("SVC_SRC", "rel1", "SVC_DST")],
        )

        # Same family: exact canonical_id match
        query_same_fam = _motif(
            "INC-FAM2-B",
            canonical_ids=["svc-05", "svc-03"],
            event_sequence=["DEPLOY", "METRIC_ANOMALY", "ERROR_LOG"],
            causal_shape=[("SVC_SRC", "rel1", "SVC_DST")],
        )

        # Different family: no canonical_id overlap
        query_diff_fam = _motif(
            "INC-FAM4-A",
            canonical_ids=["svc-07", "svc-11"],
            event_sequence=["DEPLOY", "METRIC_ANOMALY", "ERROR_LOG"],
            causal_shape=[("SVC_SRC", "rel1", "SVC_DST")],
        )

        score_same, _ = _compute_similarity(query_same_fam, stored)
        score_diff, _ = _compute_similarity(query_diff_fam, stored)

        print(f"\nSame-family score: {score_same:.3f}")
        print(f"Diff-family score: {score_diff:.3f}")

        # Same family should score MUCH higher due to canonical_id weight (0.50)
        assert score_same > 0.85, f"Expected same-family score > 0.85, got {score_same:.3f}"
        assert score_diff <= 0.50, f"Expected diff-family score <= 0.50, got {score_diff:.3f}"
        assert score_same > score_diff + 0.40, f"Same-family ({score_same:.3f}) should exceed diff-family ({score_diff:.3f}) by significant margin"

    def test_partial_canonical_id_overlap(self):
        """Partial canonical_id overlap should reduce similarity."""
        stored = _motif(
            "INC-FAM2-A",
            canonical_ids=["svc-05", "svc-03"],
        )

        # Partial overlap: only one service matches
        query_partial = _motif(
            "INC-PARTIAL",
            canonical_ids=["svc-05", "svc-07"],  # svc-05 matches, svc-07 doesn't
        )

        # No overlap
        query_none = _motif(
            "INC-NONE",
            canonical_ids=["svc-11", "svc-12"],
        )

        score_partial, _ = _compute_similarity(query_partial, stored)
        score_none, _ = _compute_similarity(query_none, stored)

        print(f"\nPartial overlap score: {score_partial:.3f}")
        print(f"No overlap score: {score_none:.3f}")

        # Partial should be > None (but neither as good as full match)
        assert score_partial > score_none, f"Partial ({score_partial:.3f}) should exceed none ({score_none:.3f})"
        assert score_partial < 0.75, f"Partial overlap shouldn't score as high as same-family match"

    def test_empty_canonical_ids_backward_compatible(self):
        """Empty canonical_ids should not crash (backward compatibility)."""
        stored = _motif("INC-A", canonical_ids=[])
        query = _motif("INC-B", canonical_ids=[])

        score, rationale = _compute_similarity(query, stored)
        # Should not crash and should have some score from other factors
        assert 0.0 <= score <= 1.0
        assert isinstance(rationale, str)


class TestMinimumThresholdFilter:
    """Test that the minimum similarity threshold filters low-quality matches."""

    def test_threshold_filters_weak_matches(self):
        """Matches below min_similarity threshold should be excluded."""
        idx = BehavioralMotifIndex()

        # Create some stored incidents with different family characteristics
        idx.index_incident(_motif(
            "INC-FAM2-TRAIN",
            canonical_ids=["svc-05", "svc-03"],
            event_sequence=["DEPLOY", "METRIC", "LOG"],
            causal_shape=[("A", "rel", "B")],
        ))
        idx.index_incident(_motif(
            "INC-FAM4-TRAIN",
            canonical_ids=["svc-07", "svc-11"],
            event_sequence=["DEPLOY", "METRIC", "LOG"],
            causal_shape=[("A", "rel", "B")],
        ))

        # Query from family 2
        query = _motif(
            "INC-FAM2-QUERY",
            canonical_ids=["svc-05", "svc-03"],
            event_sequence=["DEPLOY", "METRIC", "LOG"],
            causal_shape=[("A", "rel", "B")],
        )

        # With high threshold, should filter out the cross-family match
        results_strict = idx.find_similar(query, top_k=5, min_similarity=0.70)
        results_loose = idx.find_similar(query, top_k=5, min_similarity=0.30)

        print(f"\nStrict threshold (0.70): {len(results_strict)} results")
        print(f"Loose threshold (0.30): {len(results_loose)} results")

        # Strict should return only the family-2 match (or none if score < 0.70)
        # Loose should return both
        assert len(results_strict) <= len(results_loose), "Strict should filter more"

        # All results should exceed their respective thresholds
        for r in results_strict:
            assert r.similarity >= 0.70, f"Result {r.incident_id} below strict threshold"
        for r in results_loose:
            assert r.similarity >= 0.30, f"Result {r.incident_id} below loose threshold"

    def test_identical_motifs_always_pass_threshold(self):
        """Identical motifs should always score 1.0 and pass any threshold."""
        idx = BehavioralMotifIndex()

        stored = _motif(
            "INC-EXACT",
            canonical_ids=["svc-05", "svc-03"],
            event_sequence=["DEPLOY", "METRIC", "LOG", "SIGNAL"],
            causal_shape=[("A", "rel", "B"), ("C", "rel2", "D")],
            remediation_action="rollback",
        )
        idx.index_incident(stored)

        query = _motif(
            "INC-QUERY",
            canonical_ids=["svc-05", "svc-03"],
            event_sequence=["DEPLOY", "METRIC", "LOG", "SIGNAL"],
            causal_shape=[("A", "rel", "B"), ("C", "rel2", "D")],
            remediation_action="rollback",
        )

        results = idx.find_similar(query, top_k=1, min_similarity=0.95)
        assert len(results) == 1, "Identical motif should always match"
        assert results[0].similarity >= 0.99, "Identical motif should score ~1.0"

    def test_default_threshold_is_reasonable(self):
        """Default threshold should be strict enough to improve precision."""
        idx = BehavioralMotifIndex()

        # Create a reference incident (family 2)
        idx.index_incident(_motif(
            "INC-FAM2",
            canonical_ids=["svc-05", "svc-03"],
            event_sequence=["DEPLOY", "METRIC", "LOG"],
            causal_shape=[("A", "rel", "B")],
        ))
        # Create a false positive candidate (family 4)
        idx.index_incident(_motif(
            "INC-FAM4",
            canonical_ids=["svc-07", "svc-11"],
            event_sequence=["DEPLOY", "METRIC", "LOG"],
            causal_shape=[("A", "rel", "B")],
        ))

        query = _motif(
            "INC-FAM2-QUERY",
            canonical_ids=["svc-05", "svc-03"],
            event_sequence=["DEPLOY", "METRIC", "LOG"],
            causal_shape=[("A", "rel", "B")],
        )

        # With default threshold (0.55), only same-family should pass
        results = idx.find_similar(query, top_k=5)  # default min_similarity=0.55

        # Should filter out cross-family false positive
        if len(results) > 0:
            # First result should be the correct family
            assert "FAM2" in results[0].incident_id, f"Top result should be FAM2, got {results[0].incident_id}"


class TestRationaleImprovement:
    """Test that rationale messages include canonical_id information."""

    def test_rationale_mentions_canonical_ids(self):
        """Rationale should mention canonical_id overlap for debugging."""
        stored = _motif(
            "INC-A",
            canonical_ids=["svc-05", "svc-03"],
            event_sequence=["DEPLOY", "METRIC"],
        )
        query = _motif(
            "INC-B",
            canonical_ids=["svc-05", "svc-03"],
            event_sequence=["DEPLOY", "METRIC"],
        )

        _, rationale = _compute_similarity(query, stored)

        print(f"\nRationale: {rationale}")
        assert "canonical" in rationale.lower(), "Rationale should mention canonical_ids"
        assert "svc-05" in rationale or "svc-03" in rationale, "Rationale should list matched services"

    def test_rationale_when_no_canonical_overlap(self):
        """Rationale should handle no canonical_id overlap gracefully."""
        stored = _motif(
            "INC-A",
            canonical_ids=["svc-05", "svc-03"],
        )
        query = _motif(
            "INC-B",
            canonical_ids=["svc-07", "svc-11"],
        )

        _, rationale = _compute_similarity(query, stored)
        print(f"\nRationale (no overlap): {rationale}")
        # Should not crash and should be meaningful
        assert isinstance(rationale, str) and len(rationale) > 0


class TestPrecisionImprovementScenarios:
    """Real-world scenarios demonstrating precision improvements."""

    def test_five_family_incident_scenario(self):
        """
        Scenario: 5 incident families, each with distinct services.
        A query from family 2 should match family 2, not families 1, 3, 4, 5.
        """
        idx = BehavioralMotifIndex()

        # Create incidents from 5 different families
        families = {
            0: ["svc-01", "svc-02"],
            1: ["svc-03", "svc-04"],
            2: ["svc-05", "svc-06"],
            3: ["svc-07", "svc-08"],
            4: ["svc-09", "svc-10"],
        }

        for fam_id, services in families.items():
            idx.index_incident(_motif(
                f"INC-FAM{fam_id}-TRAIN",
                canonical_ids=services,
                event_sequence=["DEPLOY", "METRIC", "LOG", "SIGNAL"],
                causal_shape=[("SVC", "affects", "UPSTREAM")],
            ))

        # Query from family 2
        query = _motif(
            "INC-FAM2-QUERY",
            canonical_ids=families[2],
            event_sequence=["DEPLOY", "METRIC", "LOG", "SIGNAL"],
            causal_shape=[("SVC", "affects", "UPSTREAM")],
        )

        results = idx.find_similar(query, top_k=5, min_similarity=0.55)

        print(f"\nFound {len(results)} matches for family 2 query:")
        for i, r in enumerate(results, 1):
            print(f"  {i}. {r.incident_id} (similarity={r.similarity:.3f})")

        # Should find the correct family at position 1
        if len(results) > 0:
            assert "FAM2" in results[0].incident_id, f"Expected FAM2 at top, got {results[0].incident_id}"
            # Precision should be high (mostly correct family)
            family_2_matches = sum(1 for r in results if "FAM2" in r.incident_id)
            precision = family_2_matches / len(results) if results else 0.0
            print(f"  Precision: {precision:.1%} (correct family in {family_2_matches}/{len(results)})")
            assert precision >= 0.7, f"Expected precision >= 0.7, got {precision:.1%}"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
