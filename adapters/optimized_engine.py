"""Optimized Engine - Hybrid similarity with topology drift tracking.

This engine demonstrates comprehensive handling of service rename events
(topology drift) which is critical for incident matching across infrastructure
changes. Services are identified by canonical IDs, while surface names change
over time due to deployment, versioning, and infrastructure events.
"""

from typing import Iterable, Dict, List, Set, Literal, Tuple
from collections import defaultdict
from difflib import SequenceMatcher
import re
import sys
import os
from datetime import datetime

# Resolve schema imports
_HERE = os.path.dirname(os.path.abspath(__file__))
_BENCH = os.path.dirname(_HERE)
if _BENCH not in sys.path:
    sys.path.insert(0, _BENCH)

from adapter import Adapter
from schema import Context, Event, IncidentSignal

class Engine(Adapter):
    """Optimized Engine with topology drift tracking and canonical ID resolution.

    Key Feature: Service Rename Resilience
    ======================================
    Services are identified by canonical IDs (e.g., "svc-10") while their
    surface names change (e.g., "svc-10" → "svc-10-r1" → "svc-10-r2").
    This engine tracks all renames and uses canonical IDs for matching.

    When incident INC-A triggers on "svc-10-r2" and we're trying to match
    against incident INC-B that triggered on "svc-10", we correctly identify
    them as the same service using the canonical mapping.
    """

    def __init__(self, debug: bool = False):
        self.events = []
        self.incidents = {}
        self.current_incident = None

        # Topology tracking: canonical_id → set of all surface names it's had
        self.service_lineage: Dict[str, List[Tuple[str, str]]] = defaultdict(list)  # cid → [(surface_name, timestamp), ...]

        # Current alias mapping: surface_name → canonical_id
        # Example: {"svc-10-r2": "svc-10", "svc-03-r4": "svc-03"}
        self.alias_map: Dict[str, str] = {}

        # Reverse mapping: canonical_id → current_surface_name
        # Example: {"svc-10": "svc-10-r2", "svc-03": "svc-03-r4"}
        self.current_surface_names: Dict[str, str] = {}

        # Topology events history for drift reporting
        self.topology_events: List[Dict] = []

        self.past_incidents = []
        self.incident_event_patterns = defaultdict(list)
        self.debug = debug

    def _canonical(self, name: str) -> str:
        """Resolve surface name to canonical ID.

        Examples:
            "svc-10-r2" → "svc-10"  (via alias_map)
            "svc-10" → "svc-10"     (if not renamed, returns as-is)
            "" → ""
        """
        if not name:
            return ""
        # If this name is in our alias map, return its canonical form
        if name in self.alias_map:
            return self.alias_map[name]
        # Otherwise assume it's already canonical (or first occurrence)
        return name

    def get_service_lineage(self, service_name: str) -> List[Tuple[str, str]]:
        """Returns the complete lineage of a service (all names it's had).

        Args:
            service_name: Surface name or canonical ID

        Returns:
            List of (surface_name, timestamp) tuples in chronological order

        Examples:
            get_service_lineage("svc-10") → [("svc-10", "2026-05-01T..."),
                                              ("svc-10-r1", "2026-05-02T..."),
                                              ("svc-10-r2", "2026-05-03T...")]
            get_service_lineage("svc-10-r2") → [same as above]
        """
        cid = self._canonical(service_name)
        return self.service_lineage.get(cid, [])

    def get_canonical_mapping(self) -> Dict[str, str]:
        """Returns current alias → canonical mapping.

        Shows how current surface names map back to canonical IDs.

        Example:
            {
                "svc-10-r2": "svc-10",
                "svc-03-r4": "svc-03",
                "svc-08-r5": "svc-08",
                ...
            }
        """
        return dict(self.alias_map)

    def _build_drift_report(self) -> Dict:
        """Generates comprehensive topology drift report.

        Useful for understanding how infrastructure changes affect incident matching.
        """
        report = {
            "total_renames": len(self.topology_events),
            "services_affected": len(self.service_lineage),
            "current_mappings": dict(self.alias_map),
            "lineages": {},
            "timeline": []
        }

        # Build lineage summary
        for cid, lineage in self.service_lineage.items():
            report["lineages"][cid] = [
                {"surface_name": name, "timestamp": ts, "sequence": i}
                for i, (name, ts) in enumerate(lineage)
            ]

        # Build chronological timeline
        for event in self.topology_events:
            if event.get("change") == "rename":
                report["timeline"].append({
                    "timestamp": event.get("ts"),
                    "type": "rename",
                    "from": event.get("from"),
                    "to": event.get("to"),
                    "canonical_id": self._canonical(event.get("to"))
                })

        return report

    def ingest(self, events: Iterable[Event]) -> None:
        """Ingest events and track topology changes."""
        for event in events:
            self.events.append(event)
            kind = event.get("kind")

            # ===== TOPOLOGY DRIFT TRACKING =====
            if kind == "topology" and event.get("change") == "rename":
                old_name = event.get("from")
                new_name = event.get("to")
                ts = event.get("ts", "")

                # Determine canonical ID
                # If old_name is already an alias, get its canonical form
                cid = self._canonical(old_name)
                if cid == old_name:
                    # old_name wasn't in alias_map, so it's the first/canonical
                    cid = old_name

                # Initialize lineage if needed
                if cid not in self.service_lineage:
                    self.service_lineage[cid].append((cid, ts))

                # Record the new name in lineage
                self.service_lineage[cid].append((new_name, ts))

                # Update alias map: new_name → canonical_id
                self.alias_map[new_name] = cid

                # Update current surface name for this canonical ID
                self.current_surface_names[cid] = new_name

                # Record topology event for drift report
                self.topology_events.append(event)

                if self.debug:
                    print(f"[TOPOLOGY] Rename detected at {ts}:")
                    print(f"  {old_name} → {new_name}")
                    print(f"  Canonical ID: {cid}")
                    print(f"  Alias map now: {cid} ← {new_name}")
                    print(f"  Full lineage for {cid}: {[name for name, _ in self.service_lineage[cid]]}")

            # ===== INCIDENT TRACKING =====
            elif kind == "incident_signal":
                self.current_incident = event.get("incident_id")
                svc_surface = event.get("service", "")
                svc_canonical = self._canonical(svc_surface)

                self.incidents[self.current_incident] = {
                    "id": self.current_incident,
                    "trigger": event.get("trigger", ""),
                    "events": [],
                    "services": set(),
                    "services_canonical": set(),  # Track both surface and canonical
                    "event_types": [],
                    "timestamp": event.get("ts"),
                    "surface_service": svc_surface,
                    "canonical_service": svc_canonical,
                }

                if svc_canonical:
                    self.incidents[self.current_incident]["services_canonical"].add(svc_canonical)

            # ===== INCIDENT END =====
            elif kind == "remediation" and self.current_incident:
                inc = self.incidents[self.current_incident]
                inc["remediation"] = {
                    "action": event.get("action"),
                    "target": event.get("target"),
                    "outcome": event.get("outcome")
                }

                self.past_incidents.append({
                    "id": self.current_incident,
                    "trigger": inc["trigger"],
                    "event_types": inc["event_types"],
                    "services": list(inc["services"]),
                    "services_canonical": list(inc["services_canonical"]),  # Store canonical IDs
                    "remediation_action": event.get("action"),
                    "remediation_target": event.get("target"),
                    "remediation_outcome": event.get("outcome"),
                    "timestamp": event.get("ts")
                })

                pattern_key = tuple(sorted(set(inc["event_types"])))
                self.incident_event_patterns[pattern_key].append(self.current_incident)

                self.current_incident = None

            # ===== EVENT COLLECTION =====
            elif self.current_incident:
                inc = self.incidents[self.current_incident]
                inc["events"].append(event)
                inc["event_types"].append(kind)

                svc_surface = event.get("service") or event.get("svc") or event.get("target")
                if svc_surface:
                    svc_canonical = self._canonical(svc_surface)
                    inc["services"].add(svc_surface)
                    if svc_canonical:
                        inc["services_canonical"].add(svc_canonical)

    def _calculate_similarity(self, current: Dict, past: Dict) -> float:
        """Multi-strategy similarity using canonical IDs.

        CRITICAL: All service comparisons use canonical IDs, not surface names.
        This ensures that svc-10 and svc-10-r2 are correctly identified as
        the same service even though they have different surface names.

        Similarity Strategies:
        1. Alert Pattern (60%): Latency vs Error type
        2. Event Sequence (25%): Temporal event ordering
        3. Remediation (10%): Rollback pattern
        4. Canonical Service Overlap (5%): Using canonical IDs
        """
        scores = []
        weights = []

        # Strategy 1: Alert Pattern Matching (60% weight)
        current_trigger = current.get("trigger", "").lower()
        past_trigger = past.get("trigger", "").lower()

        if current_trigger and past_trigger:
            # Extract alert type
            current_pattern = None
            past_pattern = None

            if "latency" in current_trigger:
                current_pattern = "latency"
            elif "error" in current_trigger or "fail" in current_trigger:
                current_pattern = "error"

            if "latency" in past_trigger:
                past_pattern = "latency"
            elif "error" in past_trigger or "fail" in past_trigger:
                past_pattern = "error"

            # Same alert type is strong signal
            if current_pattern and past_pattern and current_pattern == past_pattern:
                scores.append(0.8)
                weights.append(0.60)
            else:
                # Fall back to term overlap
                current_terms = set(re.findall(r'\b\w+\b', current_trigger))
                past_terms = set(re.findall(r'\b\w+\b', past_trigger))
                if current_terms and past_terms:
                    term_sim = len(current_terms & past_terms) / len(current_terms | past_terms)
                    scores.append(term_sim * 0.7)
                    weights.append(0.60)

        # Strategy 2: Event Type Sequence (25% weight)
        current_types = current.get("event_types", [])
        past_types = past.get("event_types", [])

        if current_types and past_types:
            seq_sim = SequenceMatcher(None, current_types, past_types).ratio()
            scores.append(seq_sim)
            weights.append(0.25)

        # Strategy 3: Remediation Pattern (10% weight)
        past_remed = past.get("remediation_action", "")
        if past_remed == "rollback":
            scores.append(0.7)
            weights.append(0.10)

        # Strategy 4: CANONICAL Service Overlap (5% weight)
        # IMPORTANT: Compare using canonical IDs, not surface names!
        # This handles service renames transparently.
        current_services_canonical = set(current.get("services_canonical", []))
        past_services_canonical = set(past.get("services_canonical", []))

        if current_services_canonical and past_services_canonical:
            # Both use canonical IDs, so comparison is drift-resistant
            service_sim = len(current_services_canonical & past_services_canonical) / len(current_services_canonical | past_services_canonical)
            scores.append(service_sim)
            weights.append(0.05)

            if self.debug:
                overlap = current_services_canonical & past_services_canonical
                if overlap:
                    print(f"[SIMILARITY] Canonical service overlap: {overlap}")

        if not scores:
            return 0.35

        total_weight = sum(weights[:len(scores)])
        if total_weight == 0:
            return 0.35

        weighted_score = sum(s * w for s, w in zip(scores, weights)) / total_weight
        return min(0.95, max(0.0, weighted_score))

    def reconstruct_context(self, signal: IncidentSignal, mode: Literal["fast", "deep"] = "fast") -> Context:
        """Reconstruct operational context, handling service renames transparently."""
        incident_id = signal.get("incident_id")

        # Resolve signal service to canonical ID
        signal_service_surface = signal.get("service", "")
        signal_service_canonical = self._canonical(signal_service_surface)

        if self.debug and signal_service_surface:
            print(f"[CONTEXT] Signal service: {signal_service_surface} → canonical: {signal_service_canonical}")

        # Build current incident representation
        current = {
            "trigger": signal.get("trigger", ""),
            "event_types": self._infer_event_types(signal),
            "services": {signal_service_surface} if signal_service_surface else set(),
            "services_canonical": {signal_service_canonical} if signal_service_canonical else set(),
            "remediation": {}
        }

        # Find all matches
        matches = []
        for past in self.past_incidents:
            similarity = self._calculate_similarity(current, past)
            matches.append({
                "past_incident_id": past["id"],
                "similarity": similarity,
                "rationale": self._rationale(past, similarity)
            })

        # Sort by similarity
        matches.sort(key=lambda x: x["similarity"], reverse=True)

        # Take top 5 matches
        unique_matches = []
        seen = set()

        for m in matches:
            if m["past_incident_id"] not in seen:
                seen.add(m["past_incident_id"])
                unique_matches.append(m)
                if len(unique_matches) >= 5:
                    break

        # Build remediations
        remediations = []
        for match in unique_matches[:5]:
            for past in self.past_incidents:
                if past["id"] == match["past_incident_id"]:
                    remediations.append({
                        "action": past.get("remediation_action", "rollback"),
                        "target": past.get("remediation_target", "unknown"),
                        "historical_outcome": past.get("remediation_outcome", "resolved"),
                        "confidence": match["similarity"]
                    })
                    break

        # Build causal chain
        causal_chain = []
        for match in unique_matches[:min(3, len(unique_matches))]:
            cause_event_id = ""
            effect_event_id = ""
            if incident_id in self.incidents:
                events = self.incidents[incident_id].get("events", [])
                if events:
                    effect_event_id = events[0].get("event_id", events[0].get("id", ""))

            causal_chain.append({
                "cause_event_id": cause_event_id,
                "effect_event_id": effect_event_id,
                "evidence": f"Pattern match with similarity {match['similarity']:.3f}: {match['rationale']}",
                "confidence": match["similarity"]
            })

        # Get related events
        related_events = []
        if incident_id in self.incidents:
            related_events = self.incidents[incident_id].get("events", [])[:15]

        # Build similar incidents list
        similar_incidents = []
        for match in unique_matches[:5]:
            similar_incidents.append({
                "incident_id": match["past_incident_id"],
                "similarity": match["similarity"],
                "rationale": match["rationale"]
            })

        # Calculate confidence
        confidence = self._confidence(unique_matches)

        return {
            "related_events": related_events,
            "causal_chain": causal_chain,
            "similar_past_incidents": similar_incidents,
            "suggested_remediations": remediations,
            "confidence": confidence,
            "explain": self._explain(similar_incidents, confidence)
        }

    def _infer_event_types(self, signal: Dict) -> List[str]:
        """Infer event types from signal trigger."""
        trigger = signal.get("trigger", "").lower()
        types = []
        if "error" in trigger or "fail" in trigger:
            types.append("log")
        if "latency" in trigger or "timeout" in trigger:
            types.append("metric")
        if "deploy" in trigger:
            types.append("deploy")
        if "trace" in trigger:
            types.append("trace")
        return types if types else ["log", "metric"]

    def _infer_services(self, signal: Dict) -> Set[str]:
        """Infer services from signal trigger (returns surface names for reference)."""
        trigger = signal.get("trigger", "").lower()
        services = set()
        patterns = [r'([a-z]+-?(?:svc|api|service))', r'([a-z]+-svc)']
        for pattern in patterns:
            for match in re.findall(pattern, trigger):
                services.add(self._canonical(match))
        return services

    def _rationale(self, past: Dict, similarity: float) -> str:
        """Generate rationale for match."""
        action = past.get("remediation_action", "unknown")
        return f"Similar incident {past['id']} (sim={similarity:.2f}) resolved by {action}"

    def _confidence(self, matches: List[Dict]) -> float:
        """Calculate confidence score."""
        if not matches:
            return 0.5
        weighted = sum(m["similarity"] * (1.0 - i*0.2) for i, m in enumerate(matches[:5]))
        total_weight = sum(1.0 - i*0.2 for i in range(min(5, len(matches))))
        return min(0.95, weighted / total_weight if total_weight > 0 else 0.5)

    def _explain(self, incidents: List[Dict], confidence: float) -> str:
        """Generate explanation of context reconstruction."""
        if not incidents:
            return "No similar past incidents found with sufficient confidence."
        high_conf = [inc for inc in incidents if inc.get("similarity", 0) >= 0.55]
        if high_conf:
            top = high_conf[0]
            return (f"Found {len(high_conf)} high-confidence matches (confidence {confidence:.2f}). "
                    f"Best match: {top['incident_id']} with similarity {top['similarity']:.2f}. "
                    f"{top['rationale']}")
        else:
            top = incidents[0]
            return (f"Found {len(incidents)} matches (confidence {confidence:.2f}). "
                    f"Best match: {top['incident_id']} with similarity {top['similarity']:.2f}. "
                    f"{top['rationale']}")

    def close(self):
        """Cleanup."""
        pass
