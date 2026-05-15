# Mini Anvil Project Analysis — Quick Summary

## What is it?

**Mini Anvil** is an incident context engine that recognizes infrastructure failures across renames, topology changes, and different telemetry. It ingests infrastructure events and reconstructs causal context for incident response.

---

## Architecture at a Glance

### 4-Layer Stack

| Layer | Component | Technology | Job |
|-------|-----------|-----------|-----|
| 1 | **Identity Resolver** | Pure Python | Maps service names → stable canonical IDs (handles renames) |
| 2 | **Event Store** | DuckDB | Append-only temporal log indexed by (cid, ts) |
| 3 | **Operational Graph** | NetworkX DiGraph | Probabilistic causal edges with confidence scoring |
| 4 | **Context Assembler** | Pure Python + optional LLM | Combines layers 1-3 into final Context output |

---

## Key Features

✅ **Identity-agnostic reasoning** — Renames are handled at Layer 1; all downstream analysis uses canonical IDs only

✅ **Temporal causality enforcement** — Edges are only valid if `ts_src < ts_dst`

✅ **Probabilistic confidence** — Edges have confidence scores (0.0–1.0) that grow with repetition and decay with time

✅ **Remediation learning** — When an incident is resolved, related edges get a +0.10 confidence boost

✅ **Topology-independent motifs** — Past incidents are stored as abstract patterns, enabling cross-rename matching

✅ **Fast mode** — Zero LLM calls, all in-process, < 2s p95 latency

✅ **Deep mode** — One optional LLM call (GPT-4o-mini or Claude) for richer explanation

---

## Data Flow

### Ingestion
```
Events → Topology first (rename tracking) → Batch event insert → Graph/motif updates
```

### Reconstruction
```
IncidentSignal → Resolve service → Fetch window (5min) → BFS graph (2 hops) → Find similar motifs → Suggest remediations
```

---

## File Organization

```
Mini_Anvil/
├── adapters/engine.py          ← Entry point for the harness
├── engine/
│   ├── identity.py             ← Layer 1
│   ├── store.py                ← Layer 2
│   ├── graph.py                ← Layer 3
│   ├── assembler.py            ← Layer 4
│   ├── models.py               ← CausalEdge, IncidentMotif
│   └── motifs.py               ← Incident similarity matching
├── self_check.py               ← Benchmark suite (11 checks)
├── dashboard.py                ← Streamlit UI
└── requirements.txt            ← Dependencies
```

---

## Core APIs

### Engine (entry point)
```python
engine = Engine()
engine.ingest(events)                      # Process event stream (thread-safe with lock)
context = engine.reconstruct_context(      # Reconstruct context (concurrent-safe, read-only)
    signal, mode="fast"|"deep"
)
```

### IdentityResolver
```python
cid = resolver.resolve(service_name)           # Returns canonical_id
resolver.rename(old, new, ts)                  # Handle rename event
current = resolver.current_name(cid)           # Get latest name
```

### EventStore
```python
store.append(event_id, cid, ts, kind, raw)
store.get_window(cid, anchor_ts, window_s=300)  # Events in time window
```

### OperationalGraph
```python
graph.add_edge(src_cid, dst_cid, relation, evidence_id, ts_src, ts_dst)
edges = graph.get_causal_chain(cid, max_hops=2, min_confidence=0.3)
graph.reinforce_remediation(cid, incident_id, action, outcome, ts)
```

### ContextAssembler
```python
context = assembler.assemble(
    signal, mode, resolver, event_store, graph, motif_index
)
```

---

## Design Principles

1. **Canonical IDs First** — Never store raw service names downstream
2. **Temporal Causality** — Edge ordering enforced at write time
3. **Append-Only** — Events are immutable
4. **Probability Over Certainty** — Confidence scores, not booleans
5. **LLM Budget** — Zero LLM calls in fast mode, one max in deep mode
6. **Topology-Independent** — Motifs are pure structure, no service names
7. **Thread-Safe** — All shared state protected by locks

---

## Dependencies

```
duckdb==1.2.2          # Event store (Layer 2)
networkx==3.4.2        # Causal graph (Layer 3)
openai==1.82.0         # Deep mode explanation
anthropic==0.52.0      # Deep mode explanation alternative
streamlit==1.37.1      # Dashboard UI
pandas==2.2.3          # Data manipulation
plotly==5.24.1         # Visualization
```

---

## Quick Start

```bash
# Install
pip install -r requirements.txt

# Run benchmark (< 60s on clean machine)
python self_check.py --adapter adapters.engine:Engine --quick

# View report
cat report.json

# Run dashboard
streamlit run dashboard.py
```

---

## What Works

✅ All 4 layers fully implemented
✅ Entity resolution with rename tracking
✅ Temporal event storage with indexed queries
✅ Probabilistic causal graph with confidence scoring
✅ Remediation reinforcement and decay
✅ Motif extraction and similarity matching
✅ Context assembly in fast & deep modes
✅ Benchmark suite with 11 checks
✅ Thread-safe ingestion with batch inserts
✅ Streamlit dashboard (basic UI)

---

## Known Gaps

❌ **No unit tests** — Missing `tests/` directory (noted in PROJECT_STATUS.md)

❌ **Multi-relation edges** — Currently `(src, dst)` → single relation; different relations for same endpoints are skipped

❌ **Motif shape richness** — Causal shapes are 2-tuples; could be extended to 3-tuples or graph structures

❌ **Layer 4 decay API** — Minor mismatch between `ContextAssembler` call and `OperationalGraph` signature (non-breaking due to duck typing)

---

## Scalability

**L2 Scale** (~1,000 events/sec, ~100 services):
- Event ingestion: batch inserts, throughput ≥ 1,000 ev/sec
- Window queries: < 10ms (DuckDB index)
- Reconstruction: < 2s p95 (fast mode)
- Motif matching: < 50ms (< 24 stored incidents)

**Upgrade path**:
- Replace in-process DuckDB with TimescaleDB/Cassandra for distributed scale
- Use Redis or Memcached for motif index caching
- Implement online learning to tune confidence decay & remediation boost

---

## Use Cases

1. **Incident Triage** — Quickly understand what caused the issue and what fixed it before
2. **Post-Mortem Automation** — Automatic context assembly for incident reports
3. **Alert Enrichment** — Attach causal chain and historical context to alerts
4. **SRE Training** — Learn from past incident patterns and remediation success rates
5. **Cross-Team Correlation** — Track causal chains across service boundaries (via trace correlation)

---

## Next Steps (if extending)

1. Add unit test suite (10+ tests per layer)
2. Formalize relationship-synthesis algorithm documentation
3. Upgrade to MultiDiGraph for multi-relation support
4. Add distributed persistence (TimescaleDB)
5. Implement online learning loop
6. Extend explanations with root cause probability scores

---

## Documentation

- **PROJECT_OVERVIEW.md** — Detailed component breakdown, APIs, design principles
- **PROJECT_STATUS.md** — Snapshot of Layer 3 implementation work
- **README.md** — Quickstart guide
- **TODO.md** — Outstanding tasks (dashboard, tests)
- **schema.py** — TypedDict definitions

---

**TL;DR**: Mini Anvil is a well-engineered 4-layer incident context engine that maintains causal reasoning across infrastructure mutations. It's production-grade at L2 scale with clear expansion pathways.
