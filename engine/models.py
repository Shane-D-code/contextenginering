from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class CausalEdge:
    """A directed causal relationship between two canonical entities."""

    src_cid: str
    dst_cid: str
    relation: str
    confidence: float
    count: int
    first_seen: str
    last_seen: str
    evidence_ids: List[str]
    remediation_reinforced: bool = False
    reinforced_by: Optional[List[dict]] = None

    def to_dict(self) -> dict:
        return {
            "src_cid": self.src_cid,
            "dst_cid": self.dst_cid,
            "relation": self.relation,
            "confidence": float(self.confidence),
            "count": int(self.count),
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
            "evidence_ids": list(self.evidence_ids),
            "remediation_reinforced": bool(self.remediation_reinforced),
            "reinforced_by": list(self.reinforced_by or []),
        }

    def to_causal_edge(self, resolver) -> dict:
        """Convert canonical_ids back to service names for output."""
        return {
            "cause": resolver.current_name(self.src_cid),
            "effect": resolver.current_name(self.dst_cid),
            "relation": self.relation,
            "confidence": self.confidence,
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
        }

    def to_output(self, resolver) -> dict:
        """Spec-compliant output: (cause_id, effect_id, evidence, confidence) + extras."""
        return {
            # Binding spec fields
            "cause_id": self.src_cid,
            "effect_id": self.dst_cid,
            "cause_name": resolver.current_name(self.src_cid),
            "effect_name": resolver.current_name(self.dst_cid),
            "evidence": list(self.evidence_ids),   # required by spec
            "confidence": round(float(self.confidence), 3),
            # Additional context fields (non-binding but useful)
            "relation": self.relation,
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
        }



@dataclass
class IncidentMotif:
    """Abstract behavioral pattern (no service names).

    Must be constructible with no args because `OperationalGraph.extract_motif()`
    builds an empty motif and fills fields incrementally.
    """

    incident_id: str = ""
    canonical_ids: List[str] = field(default_factory=list)  # provenance only
    event_sequence: List[str] = field(default_factory=list)
    causal_shape: List[tuple] = field(default_factory=list)
    remediation_action: str = ""
    remediation_outcome: str = ""
    timestamp: str = ""
    confidence: float = 0.0
