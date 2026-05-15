"""
Anvil P-02 — Persistent Context Engine Adapter

This is the adapter.py the harness calls. Every method signature is binding.

Architecture:
  Layer 1: IdentityResolver  — canonical IDs across renames
  Layer 2: EventStore        — DuckDB temporal event log
  Layer 3: OperationalGraph  — NetworkX causal graph
  Layer 4: ContextAssembler  — fast/deep context reconstruction
"""

from __future__ import annotations

import threading
import uuid
from datetime import datetime, timedelta, timezone
from typing import Iterable, Literal

from engine.assembler import ContextAssembler
from engine.graph import OperationalGraph
from engine.identity import IdentityResolver
from engine.motifs import BehavioralMotifIndex
from engine.store import EventStore


class Engine:
    """
    Main adapter class. Implements the Anvil P-02 Adapter interface.

    Thread safety:
    - ingest() acquires a write lock (handles rename + event atomically)
    - reconstruct_context() is read-only and concurrent-safe
    """

    def __init__(self) -> None:
        self.resolver = IdentityResolver()
        self.store = EventStore()           # DuckDB in-process
        self.graph = OperationalGraph()     # NetworkX DiGraph
        self.motifs = BehavioralMotifIndex()
        self.assembler = ContextAssembler()
        self._lock = threading.Lock()
        self._open_incidents: dict[str, dict] = {}

    # ------------------------------------------------------------------
    # Ingestion
    # ------------------------------------------------------------------

    def _normalize_event(self, event: dict) -> dict:
        """
        PHASE 1: Normalize event format for spec compatibility.
        Handles field name variations from different sources.
        """
        normalized = dict(event)  # Shallow copy

        # Log events: normalize msg → message
        if normalized.get("kind") == "log":
            if "msg" in normalized and "message" not in normalized:
                normalized["message"] = normalized.pop("msg")

        # Topology events: flatten various rename formats
        if normalized.get("kind") == "topology":
            # Handle from_ → from (Python reserved word workaround in generator)
            if "from_" in normalized and "from" not in normalized:
                normalized["from"] = normalized.pop("from_")
            # Handle string change values ("rename" instead of object)
            change_val = normalized.get("change")
            if isinstance(change_val, str) and change_val.lower() == "rename":
                # Keep Annex-A format as-is: {change: "rename", from: ..., to: ...}
                pass

        # Incident/Remediation: ensure service field exists
        if normalized.get("kind") in ("incident_signal", "remediation"):
            # If no service, try to use target field
            if not normalized.get("service"):
                if normalized.get("target"):
                    normalized["service"] = normalized["target"]

        # Deploy events: ensure actor field exists
        if normalized.get("kind") == "deploy":
            if not normalized.get("actor"):
                normalized["actor"] = "system"

        return normalized

    def ingest(self, events: Iterable[dict]) -> None:
        """
        Process a stream of events. Thread-safe.
        Topology events (rename/dep shift) are processed first within the lock
        to ensure canonical_id consistency for all subsequent events.
        Uses batch inserts for throughput ≥ 1,000 ev/s.
        """
        # PHASE 1: Normalize all incoming events
        event_list = [self._normalize_event(e) for e in events]

        # Separate topology events — process them first
        topology_events = [e for e in event_list if e.get("kind") == "topology"]
        other_events = [e for e in event_list if e.get("kind") != "topology"]

        with self._lock:
            # Process topology mutations first (rename/dep changes)
            for event in topology_events:
                self._on_topology(event)

            # Resolve all canonical_ids and prepare batch insert rows
            batch_rows: list[tuple] = []
            for event in other_events:
                cid = self._resolve_cid_for_event(event)
                if not cid:
                    continue
                event_id = event.get("event_id") or event.get("id") or str(uuid.uuid4())
                ts = event.get("ts", "")
                kind = event.get("kind", "unknown")
                trace_id = event.get("trace_id")
                batch_rows.append((event_id, cid, ts, kind, trace_id, event))

            # Batch insert all events at once
            if batch_rows:
                self.store.append_batch(batch_rows)

            # Process graph/motif updates (non-storage logic)
            for event in other_events:
                kind = event.get("kind", "")
                cid = self._resolve_cid_for_event(event)
                if not cid:
                    continue
                if kind == "deploy":
                    self._on_deploy(event, cid)
                elif kind in ("log", "metric", "trace"):
                    self._on_signal(event, cid)
                elif kind == "incident_signal":
                    self._on_incident(event, cid)
                elif kind == "remediation":
                    self._on_remediation(event, cid)

    def _resolve_cid_for_event(self, event: dict) -> str:
        """
        Resolve canonical_id for any event kind.

        Priority order:
          1. service / svc field (most events)
          2. target field (remediation events from Annex A JSONL)
          3. incident_id lookup via open incidents (incident_signal / remediation
             when the service field is omitted — canonical Annex A format)
          4. Return "" to signal "skip this event"
        """
        service = event.get("service", event.get("svc", ""))
        if service:
            return self.resolver.resolve(service)

        kind = event.get("kind", "")

        # Annex-A remediation: use `target` field
        target = event.get("target", "")
        if target:
            return self.resolver.resolve(target)

        # Annex-A incident_signal / remediation with no service/target:
        # look up which entity owns the open incident
        inc_id = event.get("incident_id", "")
        if inc_id and kind in ("incident_signal", "remediation"):
            if inc_id in self._open_incidents:
                return self._open_incidents[inc_id]["cid"]
            # incident_signal with no prior context — register a placeholder
            # keyed on incident_id so subsequent remediation finds it
            if kind == "incident_signal":
                trigger = event.get("trigger", "")
                # Extract a service hint from the trigger string if possible
                # e.g. "alert:checkout-api/error-rate>5%" → "checkout-api"
                if trigger and ":" in trigger:
                    hint = trigger.split(":", 1)[1].split("/")[0].strip()
                    if hint:
                        return self.resolver.resolve(hint)

        return ""

    def _on_topology(self, event: dict) -> None:
        """Handle topology mutation events (rename, dependency shift).

        Supports two wire formats:
          A) Annex-A canonical:  {change: "rename", from: "old", to: "new"}
          B) Internal/extended:  {mutation: {kind: "rename", old_name: "old", new_name: "new"}}
        """
        ts = event.get("ts", "")

        # --- Format A: flat canonical (from Annex A JSONL) ---
        change_val = event.get("change", "")
        if change_val:
            change_kind = str(change_val).lower()
            if change_kind == "rename":
                old_name = event.get("from", "")
                new_name = event.get("to", "")
                if old_name and new_name:
                    self.resolver.rename(old_name, new_name, ts)
            elif change_kind in ("dep_add", "dep_remove", "dependency"):
                self.resolver.resolve(event.get("src", event.get("source", "")) or "")
                self.resolver.resolve(event.get("dst", event.get("target", "")) or "")
            return

        # --- Format B: mutation dict (internal / extended) ---
        mutation = event.get("mutation")
        if not mutation:
            mutation = event

        if isinstance(mutation, dict):
            kind = mutation.get("kind", mutation.get("type", ""))
        else:
            # mutation is a scalar (e.g. the string "rename")
            kind = str(mutation)

        if kind == "rename" or "rename" in str(mutation):
            if isinstance(mutation, dict):
                old_name = mutation.get("old_name", mutation.get("from", ""))
                new_name = mutation.get("new_name", mutation.get("to", ""))
            else:
                old_name = event.get("old_name", event.get("from", ""))
                new_name = event.get("new_name", event.get("to", ""))
            if old_name and new_name:
                self.resolver.rename(old_name, new_name, ts)
        elif kind in ("dep_add", "dep_remove", "dependency"):
            if isinstance(mutation, dict):
                src = mutation.get("src", mutation.get("source", ""))
                dst = mutation.get("dst", mutation.get("target", ""))
            else:
                src = event.get("src", "")
                dst = event.get("dst", "")
            if src:
                self.resolver.resolve(src)
            if dst:
                self.resolver.resolve(dst)

        # Store topology event in event store
        cid = self.resolver.resolve(event.get("service", event.get("src", "topology")))
        event_id = event.get("event_id") or event.get("id") or str(uuid.uuid4())
        ts = event.get("ts", "")
        self.store.append(
            event_id=event_id,
            canonical_id=cid,
            ts=ts,
            kind="topology",
            raw=event,
            trace_id=None,
        )

    def _process_event(self, event: dict) -> None:
        """Process a non-topology event."""
        kind = event.get("kind", "")
        service = event.get("service", event.get("svc", ""))

        if not service:
            return  # Skip events without a service identifier

        # Resolve service name → canonical_id (CRITICAL STEP)
        cid = self.resolver.resolve(service)

        # Store in temporal event store
        self._store_event(event, cid)

        # Route to appropriate handler
        if kind == "deploy":
            self._on_deploy(event, cid)
        elif kind in ("log", "metric", "trace"):
            self._on_signal(event, cid)
        elif kind == "incident_signal":
            self._on_incident(event, cid)
        elif kind == "remediation":
            self._on_remediation(event, cid)
        # Unknown kinds: log and continue (never crash)

    def _store_event(self, event: dict, cid: str) -> None:
        """Write event to temporal store with canonical_id tag."""
        event_id = event.get("event_id") or event.get("id") or str(uuid.uuid4())
        ts = event.get("ts", "")
        kind = event.get("kind", "unknown")
        trace_id = event.get("trace_id")

        self.store.append(
            event_id=event_id,
            canonical_id=cid,
            ts=ts,
            kind=kind,
            raw=event,
            trace_id=trace_id,
        )

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def _on_deploy(self, event: dict, cid: str) -> None:
        """Record deploy timestamp for this entity. Used as causal chain start."""
        version = event.get("version", "unknown")
        ts = event.get("ts", "")
        self.graph.record_deploy(cid, version, ts)

    def _on_signal(self, event: dict, cid: str) -> None:
        """
        Process metric/log/trace signals.
        If a recent deploy exists for this entity, add deploy→signal causal edge.
        For traces, correlate spans to build upstream call edges.
        """
        ts = event.get("ts", "")
        kind = event.get("kind", "signal")

        # Check: does this signal follow a recent deploy for cid?
        # Use 3600s (1 hour) window to capture deploy→latency spike patterns in generator
        recent_deploy = self.graph.get_recent_deploy(cid, ts, window_s=3600)
        if recent_deploy:
            self.graph.add_edge(
                src_cid=cid,
                dst_cid=cid,
                relation=f"deploy_to_{kind}",
                evidence_id=event.get("trace_id") or event.get("event_id") or ts,
                ts_src=recent_deploy["ts"],
                ts_dst=ts,
            )

        # Trace correlation: spans sharing trace_id → upstream call edges
        if event.get("trace_id") and kind == "trace":
            for span in event.get("spans", []):
                span_svc = span.get("svc", span.get("service", ""))
                if not span_svc:
                    continue
                span_cid = self.resolver.resolve(span_svc)
                if span_cid != cid:
                    span_ts = span.get("ts", "")
                    # Ensure ts_dst is strictly after ts_src
                    if not span_ts or span_ts <= ts:
                        try:
                            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                            span_ts = (dt + timedelta(seconds=1)).isoformat()
                        except Exception:
                            span_ts = ""
                    if span_ts:
                        self.graph.add_edge(
                            src_cid=cid,
                            dst_cid=span_cid,
                            relation="upstream_call",
                            evidence_id=event["trace_id"],
                            ts_src=ts,
                            ts_dst=span_ts,
                        )

        # Log error signals: if error level, add signal→incident edge candidate
        if kind == "log" and event.get("level") in ("error", "critical", "fatal"):
            # Check if there's an open incident for this entity
            for inc_id, inc in self._open_incidents.items():
                if inc.get("cid") == cid:
                    inc_ts = inc.get("ts", "")
                    # Incident opened first (ts_src=inc_ts) → error log seen after (ts_dst=ts)
                    if inc_ts and inc_ts < ts:
                        self.graph.add_edge(
                            src_cid=cid,
                            dst_cid=cid,
                            relation="error_log_during_incident",
                            evidence_id=event.get("event_id") or ts,
                            ts_src=inc_ts,
                            ts_dst=ts,
                        )

    def _on_incident(self, event: dict, cid: str) -> None:
        """Open an incident window for this entity."""
        incident_id = event.get("incident_id", str(uuid.uuid4()))
        self._open_incidents[incident_id] = {
            "cid": cid,
            "ts": event.get("ts", ""),
            "trigger": event.get("trigger", ""),
        }

    def _on_remediation(self, event: dict, cid: str) -> None:
        """
        Close an incident window. If outcome=resolved, reinforce causal edges,
        reinforce successful memory patterns, and index the completed incident.

        MEMORY EVOLUTION: When a remediation succeeds, we boost confidence of
        matching patterns so the engine learns what works.
        """
        inc_id = event.get("incident_id", "")
        outcome = event.get("outcome", "unknown")
        ts = event.get("ts", "")
        success = outcome == "resolved"

        if success:
            self.graph.reinforce_remediation(
                cid=cid,
                incident_id=inc_id,
                action=event.get("action", "unknown"),
                outcome=outcome,
                ts=ts,
                window_s=3600,
            )

            # Index this as a completed incident motif
            edges = self.graph.get_causal_chain(cid, max_hops=2)
            motif = self.graph.extract_motif(edges)
            motif.incident_id = inc_id
            motif.remediation_action = event.get("action", "")
            motif.remediation_outcome = outcome
            motif.timestamp = ts
            if cid not in motif.canonical_ids:
                motif.canonical_ids.append(cid)

            # MEMORY EVOLUTION: Store with timestamp for aging
            self.motifs.index_incident(motif, timestamp=ts)

            # MEMORY EVOLUTION: Reinforce patterns that worked
            # When a remediation succeeds, boost confidence of the pattern
            # that matched this incident. This teaches the engine.
            self.motifs.apply_reinforcement(
                incident_id=inc_id,
                success=True,
                timestamp=ts
            )
        else:
            # Remediation failed: penalty to matching patterns
            self.motifs.apply_reinforcement(
                incident_id=inc_id,
                success=False,
                timestamp=ts
            )

        # Close the incident window
        if inc_id in self._open_incidents:
            del self._open_incidents[inc_id]

    # ------------------------------------------------------------------
    # Context reconstruction
    # ------------------------------------------------------------------

    def reconstruct_context(
        self,
        signal: dict,
        mode: Literal["fast", "deep"] = "fast",
    ) -> dict:
        """
        Reconstruct context for an incident signal.
        Reads are concurrent-safe with the append-only store.

        MEMORY EVOLUTION: Before matching, apply confidence decay to patterns.
        This ensures older patterns have lower confidence, allowing the engine
        to adapt to changing infrastructure.
        """
        # Apply memory evolution: decay old patterns
        # This happens lazily (only when needed) for efficiency
        anchor_ts = signal.get("ts", "")
        if anchor_ts:
            self.motifs.apply_decay(anchor_ts)

        return self.assembler.assemble(
            signal=signal,
            mode=mode,
            resolver=self.resolver,
            event_store=self.store,
            graph=self.graph,
            motif_index=self.motifs,
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        self.store.close()
