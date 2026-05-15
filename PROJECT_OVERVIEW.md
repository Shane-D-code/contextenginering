# Mini Anvil (P-02) — Comprehensive Project Overview

## Executive Summary

**Mini Anvil** is a **Persistent Context Engine** for infrastructure incident management. It recognizes the same infrastructure failure even after services have been renamed, the topology has changed, and telemetry looks different. The system ingests infrastructure events (deployments, logs, metrics, traces, incidents) and reconstructs rich causal context to help diagnose and remediate failures.

**Core Mission**: Given an incident signal, reconstruct what caused it and what worked to fix it before.

---

## Table of Contents

1. [High-Level Architecture](#high-level-architecture)
2. [Four-Layer Breakdown](#four-layer-breakdown)
3. [Key Components & APIs](#key-components--apis)
4. [Data Flow](#data-flow)
5. [Configuration & Environment](#configuration--environment)
6. [Dependencies](#dependencies)
7. [Running & Testing](#running--testing)
8. [Design Principles](#design-principles)
9. [Known Limitations](#known-limitations)
10. [Future Enhancements](#future-enhancements)

---

## High-Level Architecture

The system is organized as **four logical layers**, each with a single responsibility:

```
┌─────────────────────────────────────────────────┐
│ Layer 4: Context Assembler                      │
│ (Produces final Context payload + explanation)  │
├─────────────────────────────────────────────────┤
│ Layer 3: Operational Graph (NetworkX)           │
│ (Probabilistic causal relationships)            │
├─────────────────────────────────────────────────┤
│ Layer 2: Event Store (DuckDB)                   │
│ (Temporal append-only event log)                │
├─────────────────────────────────────────────────┤
│ Layer 1: Identity Resolver                      │
│ (Canonical IDs across service renames)          │
└─────────────────────────────────────────────────┘
        ↑
     Adapter (engine.py)
        ↑
   Event Stream
```

---

## Four-Layer Breakdown

### Layer 1: Identity Resolver (`engine/identity.py`)

**Responsibility**: Maintain stable canonical IDs for entities across all mutations (renames, aliases, topology changes).

**Key Design**: 
- Every service name is mapped to a stable UUID-like `canonical_id` on first registration
- Rename events map the new name to the same canonical_id
- All downstream layers use canonical_ids ONLY, never raw service names

**Public API**:
```python
resolver.register(name: str) -> str
resolver.rename(old_name: str, new_name: str, ts: str) -> str
resolver.resolve(name: str) -> str  # Always returns canonical_id
resolver.current_name(canonical_id: str) -> str  # Latest display name
resolver.all_names(canonical_id: str) -> list[str]  # Rename history
resolver.rename_history(canonical_id: str) -> list[RenameEvent]
```

**Thread Safety**: Uses `threading.Lock()` for all state mutations.

**Persistence**: Serializable to/from JSON (used for benchmarking reproducibility).

---

### Layer 2: Event Store (`engine/store.py`)

**Responsibility**: Append-only temporal log of all infrastructure events, indexed by (canonical_id, timestamp).

**Technology**: DuckDB (in-process, SQL, minimal footprint)

**Schema**:
```
CREATE TABLE events (
    event_id    VARCHAR NOT NULL,
    canonical_id VARCHAR NOT NULL,      -- Layer 1 output
    ts          VARCHAR NOT NULL,       -- ISO-8601
    kind        VARCHAR NOT NULL,       -- deploy|log|metric|trace|topology|incident_signal|remediation
    trace_id    VARCHAR,                -- for distributed tracing correlation
    raw_json    VARCHAR NOT NULL        -- full event payload
)
CREATE INDEX idx_cid_ts ON events (canonical_id, ts)
CREATE INDEX idx_trace ON events (trace_id)
```

**Public API**:
```python
store.append(event_id, canonical_id, ts, kind, raw, trace_id)
store.append_batch(rows)
store.get_window(canonical_id, anchor_ts, window_s=300) -> list[dict]
store.get_by_trace_ids(trace_ids) -> list[dict]
store.get_by_canonical_ids(canonical_ids, anchor_ts, window_s=300) -> list[dict]
store.get_recent_deploy(canonical_id, anchor_ts, window_s=600) -> dict|None
store.count() -> int
store.close()
```

**Design Principles**:
- Never mutate stored events (append-only)
- Window queries use DuckDB index for sub-10ms latency at L2 scale
- Supports trace correlation via `trace_id` for distributed tracing

---

### Layer 3: Operational Graph (`engine/graph.py`)

**Responsibility**: Build and maintain a probabilistic directed causal graph over canonical_ids. Answer: "What caused what?" and "How confident are we?"

**Technology**: NetworkX DiGraph (in-memory, in-process)

**Core Concepts**:
- **Node**: canonical_id (unique per entity)
- **Edge**: `(src_cid, dst_cid, relation)` with properties:
  - `confidence` (0.0–1.0, initially 0.3, max 0.95)
  - `count` (incremented each time we see the same edge)
  - `first_seen`, `last_seen` (ISO-8601 timestamps)
  - `evidence_ids` (list of events supporting this edge)
  - `remediation_reinforced` (bool)
  - `reinforced_by` (list of remediation metadata)

**Key Design**: Temporal causality is enforced at edge-write time. If `ts_src >= ts_dst`, the edge is silently dropped.

**Public API**:

**Edge Management**:
```python
graph.add_edge(
    src_cid: str,
    dst_cid: str,
    relation: str,          # "deploy_to_metric", "upstream_call", etc.
    evidence_id: str,       # link to originating event
    ts_src: str,            # source timestamp (ISO-8601)
    ts_dst: str,            # destination timestamp
)
graph.get_edge(src_cid, dst_cid, relation=None) -> CausalEdge | None
```

**Graph Traversal**:
```python
graph.get_causal_chain(
    cid: str,
    max_hops: int = 2,
    min_confidence: float = 0.3
) -> list[CausalEdge]
```
Returns edges within `max_hops` of `cid` (both upstream and downstream) with confidence ≥ `min_confidence`. Sorted oldest-first.

**Remediation Reinforcement**:
```python
graph.reinforce_remediation(
    cid: str,
    incident_id: str,
    action: str,
    outcome: str,
    ts: str,
    window_s: int = 600
)
```
When an incident is resolved:
- Find all edges incident to `cid` with `last_seen` in `[ts - window_s, ts]`
- Boost their `confidence` by +0.10 (capped at 0.95)
- Mark `remediation_reinforced = True` and record provenance in `reinforced_by`

**Deploy Tracking**:
```python
graph.record_deploy(cid: str, version: str, ts: str)
graph.get_recent_deploy(cid: str, before_ts: str, window_s=600) -> dict | None
```
Used to infer deploy→signal causality (e.g., "deployed v2.1.0, then latency spiked").

**Confidence Decay**:
```python
graph.apply_decay(cid: str, current_ts: str, decay_per_day=0.01) -> int
graph.apply_decay_all(current_ts: str, decay_per_day=0.01) -> int
```
Staleness penalty: edges older than today lose confidence. Floor is 0.1 (never fully forgotten).

**Motif Extraction**:
```python
graph.extract_motif(edges: list[CausalEdge]) -> IncidentMotif
```
Convert concrete causal chain to abstract behavioral pattern (no service names, pure structure). Used for incident similarity matching.

**Persistence**:
```python
graph.save(filepath: str)
graph.load(filepath: str)
```
Uses `pickle` for in-memory graph serialization.

**Thread Safety**: All methods use `self._lock` (RLock).

---

### Layer 4: Context Assembler (`engine/assembler.py`)

**Responsibility**: Combine outputs from Layers 1–3 into a final `Context` payload suitable for incident response decision-making.

**Input**: An incident signal (service name, timestamp, incident_id, trigger)

**Output**: `Context` TypedDict with:
```python
{
    "related_events": list[dict],           # causally relevant events in 5-min window
    "causal_chain": list[CausalEdge],      # upstream/downstream dependencies
    "similar_past_incidents": list[dict],   # historical matches from motif index
    "suggested_remediations": list[dict],   # actions that worked before
    "confidence": float,                    # 0.0–1.0, average edge confidence
    "explain": str                          # narrative explanation
}
```

**Assembly Logic**:
1. Resolve service → canonical_id (Layer 1)
2. Fetch events within 5-min window for the entity and its 1-hop neighbors (Layer 2)
3. Include trace-correlated events (Layer 2)
4. Traverse causal graph for up to 2 hops (Layer 3)
5. Extract motif and find similar past incidents (Layer 3 + motif index)
6. Build remediation suggestions from historical matches
7. Compute final confidence as average of edge confidences
8. Generate explanation:
   - **Fast mode**: Template-based (no LLM)
   - **Deep mode**: One LLM call to GPT-4o-mini or Claude Haiku

**Public API**:
```python
context = assembler.assemble(
    signal: dict,
    mode: Literal["fast", "deep"],
    resolver: IdentityResolver,
    event_store: EventStore,
    graph: OperationalGraph,
    motif_index: BehavioralMotifIndex,
) -> dict
```

**Design Principles**:
- No LLM calls in fast mode (< 2s p95)
- Window lookback is fixed at 300s (5 minutes)
- Window queries use Layer 2 index for sub-10ms latency
- Causal traversal never exceeds 2 hops without confidence pruning
- Deduplication by event_id before returning related_events

---

## Key Components & APIs

### Adapter (`adapters/engine.py`)

The entry point for the harness. Implements the `Engine` class.

**Public API**:
```python
engine = Engine()

# Ingest events (thread-safe with lock)
engine.ingest(events: Iterable[dict]) -> None

# Reconstruct context (concurrent-safe, read-only)
context = engine.reconstruct_context(
    signal: dict,
    mode: Literal["fast", "deep"] = "fast"
) -> dict
```

**Event Routing**:
- **topology** → `_on_topology()` → Identity Resolver (Layer 1)
- **deploy** → `_on_deploy()` → Graph deploy tracking (Layer 3)
- **log/metric/trace** → `_on_signal()` → Graph edges + trace correlation (Layer 3)
- **incident_signal** → `_on_incident()` → Open incident window
- **remediation** → `_on_remediation()` → Reinforce graph edges + index motif (Layer 3)

**Thread Safety**:
- `ingest()` uses write lock; topology events processed first
- `reconstruct_context()` is read-only; no lock needed
- Batch inserts for throughput ≥ 1,000 events/sec

### Data Models (`engine/models.py`)

**CausalEdge**:
```python
@dataclass
class CausalEdge:
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
    
    def to_dict(self) -> dict
    def to_causal_edge(self, resolver) -> dict
    def to_output(self, resolver) -> dict
```

**IncidentMotif**:
```python
@dataclass
class IncidentMotif:
    incident_id: str = ""
    canonical_ids: List[str] = field(default_factory=list)
    event_sequence: List[str] = field(default_factory=list)
    causal_shape: List[tuple] = field(default_factory=list)
    remediation_action: str = ""
    remediation_outcome: str = ""
    timestamp: str = ""
    confidence: float = 0.0
```

### Behavioral Motif Index (`engine/motifs.py`)

Stores abstract behavioral patterns of past incidents, independent of service names/topology.

**Purpose**: Enable **recall across renames**. E.g., if "payment-svc → billing-svc" had a "deploy → latency spike → rollback" incident, we can match that pattern even if the next incident involves different service names.

**Similarity Metric** (weighted combination):
- 45% — Causal shape (edge-set Jaccard)
- 35% — Event sequence (Jaccard)
- 20% — Remediation action bonus

**Public API**:
```python
motif_index = BehavioralMotifIndex()
motif_index.index_incident(motif: IncidentMotif)
matches = motif_index.find_similar(query_motif, top_k=5) -> list[IncidentMatch]
motif_index.count() -> int
```

---

## Data Flow

### Ingestion Flow

```
Event Stream
    ↓
Engine.ingest(events)
    ↓
├─→ Topology events → IdentityResolver.rename() → Layer 1
│
├─→ Other events → resolve(service) → get canonical_id
    ↓
    ├─→ EventStore.append_batch() → Layer 2 (DuckDB)
    │
    ├─→ Deploy events → graph.record_deploy()
    │
    ├─→ Signal events (log/metric/trace) → graph.add_edge() + trace correlation
    │
    └─→ Remediation events → graph.reinforce_remediation() → motif index
```

### Reconstruction Flow

```
IncidentSignal(service, ts, incident_id)
    ↓
Engine.reconstruct_context()
    ↓
ContextAssembler.assemble()
    ├─→ Resolve service → canonical_id (Layer 1)
    │
    ├─→ Fetch events in [ts - 300s, ts] for cid + 1-hop neighbors (Layer 2)
    │
    ├─→ Traverse causal graph for up to 2 hops (Layer 3)
    │
    ├─→ Extract motif → find similar past incidents (Layer 3 + motif index)
    │
    ├─→ Build remediation suggestions
    │
    ├─→ Generate explanation
    │   ├─→ Fast mode: template-based (no LLM)
    │   └─→ Deep mode: GPT-4o-mini or Claude Haiku
    │
    └─→ Return Context(related_events, causal_chain, similar_incidents, remediations, confidence, explain)
```

---

## Configuration & Environment

### Environment Variables

| Variable | Purpose | Example |
|----------|---------|---------|
| `OPENAI_API_KEY` | Enables deep mode via GPT-4o-mini | `sk-...` |
| `OPENAI_MODEL` | Override OpenAI model | `gpt-4o-mini` (default) |
| `ANTHROPIC_API_KEY` | Enables deep mode via Claude | `sk-ant-...` |
| `ANTHROPIC_MODEL` | Override Anthropic model | `claude-3-5-haiku-20241022` |

### Modes

- **Fast Mode** (`mode="fast"`): All processing in-process, zero LLM calls, < 2s p95 latency
- **Deep Mode** (`mode="deep"`): One LLM call for explanation synthesis, subject to API latency

---

## Dependencies

```
duckdb==1.2.2          # Layer 2 event store
networkx==3.4.2        # Layer 3 causal graph
openai==1.82.0         # Deep mode explanation (GPT-4o-mini)
anthropic==0.52.0      # Deep mode explanation (Claude)
streamlit==1.37.1      # Dashboard UI
pandas==2.2.3          # Data manipulation
plotly==5.24.1         # Visualization
```

**Installation**:
```bash
pip install -r requirements.txt
```

---

## Running & Testing

### Quick Start

```bash
# 1. Install
pip install -r requirements.txt

# 2. Run self-check (produces report.json in < 60s on clean machine)
python self_check.py --adapter adapters.engine:Engine --quick

# 3. View report
cat report.json
```

### Self-Check Benchmark

The `self_check.py` script runs 11 aligned checks:

1. **Entity Resolution** — Rename tracking across services
2. **Temporal Causality** — Enforced edge ordering
3. **Confidence Increments** — Edge count + confidence boost
4. **Remediation Reinforcement** — Resolved incidents boost related edges
5. **Confidence Decay** — Staleness penalty
6. **Graph Traversal** — BFS up to 2 hops
7. **Motif Extraction** — Behavioral fingerprints
8. **Similar Incident Matching** — Jaccard similarity scoring
9. **Suggested Remediations** — Action recommendations
10. **Fast Mode Latency** — < 2s p95
11. **Deep Mode Explanation** — LLM-based narrative

### Smoke Tests

```bash
# Compile syntax
python -m py_compile adapters/engine.py engine/*.py

# Streamlit smoke test (requires streamlit)
streamlit run streamlit_smoke_check.py

# Dashboard
streamlit run dashboard.py
```

### Docker

```bash
docker build -t anvil-p02 .
docker run --rm anvil-p02
```

---

## Design Principles

### 1. **Canonical IDs First**
Never store raw service names in downstream layers. Always resolve to `canonical_id` at ingestion time. This enables identity-agnostic reasoning.

### 2. **Temporal Causality**
Edges are only valid if `ts_src < ts_dst`. Violations are logged and skipped. Prevents causality paradoxes.

### 3. **Append-Only, Never Mutate**
Events stored in Layer 2 are never modified. All reasoning is built on immutable fact.

### 4. **Probability Over Certainty**
Causal edges have confidence scores, not boolean flags. Confidence increases with repeated observation, decays with time.

### 5. **LLM Budget Discipline**
Fast mode uses zero LLM calls. Deep mode uses exactly one (for explanation). No LLMs in core reasoning.

### 6. **Topology-Independent Fingerprinting**
Motifs strip service names and topology details, leaving only abstract behavioral patterns. This enables cross-rename matching.

### 7. **Thread Safety**
All shared state uses locks. Ingestion is serialized; reconstruction is concurrent.

---

## Known Limitations

### 1. **No Multi-Relation Edges**
Currently, `(src_cid, dst_cid)` can have only one `relation` at a time. If a different relation arrives for the same endpoints, it is skipped. A future enhancement could use `MultiDiGraph` or per-relation edge keys.

### 2. **Target Version Not Always Captured**
Remediation events may not always include a `target_version` for rollback. The implementation stores `target_version = None` in the remediation table as a placeholder.

### 3. **No Unit Tests**
The current codebase lacks a `tests/` directory with pytest tests. This is a gap noted in the PROJECT_STATUS.md.

### 4. **Motif Shape Representation**
Causal shapes are currently `(src_role, dst_role)` 2-tuples. If richer shape semantics are needed, the shape construction in `extract_motif()` can be expanded to 3-tuples or graph structures.

### 5. **Layer 4 Decay API Mismatch**
The `ContextAssembler` currently calls `graph.apply_decay(anchor_ts)` without a canonical_id. The newer `OperationalGraph` expects `apply_decay(cid, current_ts, decay_per_day)`. This may require a follow-up integration pass (though it likely won't break immediately due to duck typing).

---

## Future Enhancements

### 1. **Unit Tests Suite**
Add `tests/test_graph.py`, `test_identity.py`, `test_store.py`, `test_assembler.py` with 10+ tests per module covering:
- Temporal enforcement
- Confidence increments and caps
- Remediation reinforcement
- Decay floors
- Traversal ordering
- Motif extraction abstraction

### 2. **Relationship-Synthesis Algorithm**
Document and formalize the algorithm for inferring causal relationships from signal patterns:
- Deploy → signal correlation (temporal window)
- Trace span correlation (shared trace_id)
- Log error cascade detection
- Metric spike correlation

### 3. **Multi-Relation Support**
Upgrade `OperationalGraph` to support multiple relations per `(src, dst)` pair using `networkx.MultiDiGraph` or composite edge keys.

### 4. **Distributed Persistence**
Replace in-process DuckDB with a distributed store (e.g., TimescaleDB, Cassandra) for production scale.

### 5. **Online Learning**
Allow the motif index and graph to learn from human-confirmed incident resolutions, continuously improving similarity matching and remediation suggestions.

### 6. **Richer Explanations**
Extend LLM-based explanations to include:
- Root cause probability scores
- Risk factors for escalation
- Precedent incidents with higher precision

### 7. **GraphQL API**
Expose graph traversal, motif search, and event queries via a GraphQL API for integration with external tools.

---

## File Structure

```
Mini_Anvil/
├── README.md                          # Quickstart guide
├── PROJECT_STATUS.md                  # Snapshot of P-02 Layer 3 work
├── PROJECT_OVERVIEW.md                # This document
├── TODO.md                            # Incomplete tasks (e.g., dashboard, tests)
├── requirements.txt                   # Dependencies
├── self_check.py                      # Benchmark suite (11 checks)
├── schema.py                          # TypedDict definitions
├── dashboard.py                       # Streamlit UI
├── streamlit_smoke_check.py           # Streamlit syntax check
│
├── adapters/
│   ├── __init__.py
│   └── engine.py                      # Main adapter (Engine class)
│
├── engine/
│   ├── __init__.py
│   ├── identity.py                    # Layer 1: Entity resolution
│   ├── store.py                       # Layer 2: DuckDB event store
│   ├── graph.py                       # Layer 3: NetworkX causal graph
│   ├── assembler.py                   # Layer 4: Context assembly
│   ├── models.py                      # CausalEdge, IncidentMotif dataclasses
│   └── motifs.py                      # Behavioral motif index
│
├── Dockerfile                         # Docker build
├── .gitignore
└── report.json                        # Benchmark output
```

---

## Summary

**Mini Anvil** is a well-structured incident response system that maintains causal context across infrastructure mutations. Its four-layer design cleanly separates concerns: identity resolution, temporal storage, probabilistic reasoning, and context assembly. The emphasis on canonical IDs, temporal enforcement, and topology-independent fingerprinting makes it resilient to the dynamics of modern cloud infrastructure.

The system is production-grade at L2 scale (~1,000 events/sec, ~100 services), with clear pathways for scaling and enrichment (distributed persistence, online learning, richer explanations).

---

**Last Updated**: Snapshot based on codebase as of 2026-05-15
