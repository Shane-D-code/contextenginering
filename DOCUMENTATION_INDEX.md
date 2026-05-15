# Mini Anvil Documentation Index

## 📚 Complete Documentation Map

This document provides a guide to all documentation resources for the **Mini Anvil** persistent context engine project.

---

## 1. **START HERE** 👇

### [`ANALYSIS_SUMMARY.md`](ANALYSIS_SUMMARY.md) — The Quick Reference
**Best for**: Getting a bird's-eye view in 5 minutes
- What Mini Anvil does
- 4-layer architecture at a glance
- Key features checklist
- Core APIs in brief
- Known gaps
- Quick start commands

**Read this first if you**: Want to understand the project quickly without diving into details.

---

## 2. **Deep Dives**

### [`PROJECT_OVERVIEW.md`](PROJECT_OVERVIEW.md) — The Complete Manual
**Best for**: Comprehensive understanding of every component
- Detailed breakdown of all 4 layers (Layer 1–4)
- Every public API with signatures
- Data models (CausalEdge, IncidentMotif)
- Behavioral motif index
- Data flow (ingestion + reconstruction)
- Configuration & environment variables
- Dependencies explained
- Design principles & rationale
- Known limitations
- Future enhancements
- File structure

**Read this when you**: Need to understand component APIs, design decisions, or troubleshoot behavior.

**Sections**:
- [High-Level Architecture](PROJECT_OVERVIEW.md#high-level-architecture)
- [Layer 1: Identity Resolver](PROJECT_OVERVIEW.md#layer-1-identity-resolver-engineidentitypy)
- [Layer 2: Event Store](PROJECT_OVERVIEW.md#layer-2-event-store-enginestonepy)
- [Layer 3: Operational Graph](PROJECT_OVERVIEW.md#layer-3-operational-graph-enginegraphpy)
- [Layer 4: Context Assembler](PROJECT_OVERVIEW.md#layer-4-context-assembler-engineassemblerpy)
- [Data Flow](PROJECT_OVERVIEW.md#data-flow)
- [Design Principles](PROJECT_OVERVIEW.md#design-principles)

---

### [`ARCHITECTURE_DIAGRAMS.md`](ARCHITECTURE_DIAGRAMS.md) — Visual Reference
**Best for**: Understanding system architecture visually
- 4-layer stack diagram with data flow
- Event ingestion flow
- Context reconstruction flow
- Causal edge lifecycle
- Identity resolver rename tracking
- Motif extraction & similarity example
- Confidence scoring & decay
- Thread safety model
- Component dependency graph
- Query latency profile

**Read this when you**: Want to visualize how components interact or understand specific processes.

**Diagrams**:
1. [Four-Layer Stack](ARCHITECTURE_DIAGRAMS.md#1-four-layer-stack-with-data-flow)
2. [Event Ingestion Flow](ARCHITECTURE_DIAGRAMS.md#2-event-ingestion-flow)
3. [Context Reconstruction Flow](ARCHITECTURE_DIAGRAMS.md#3-context-reconstruction-flow)
4. [Causal Edge Lifecycle](ARCHITECTURE_DIAGRAMS.md#4-causal-edge-lifecycle)
5. [Identity Resolver Rename Tracking](ARCHITECTURE_DIAGRAMS.md#5-identity-resolver-rename-tracking)
6. [Motif Extraction & Similarity](ARCHITECTURE_DIAGRAMS.md#6-motif-extraction--similarity)
7. [Confidence Scoring & Decay](ARCHITECTURE_DIAGRAMS.md#7-confidence-scoring--decay)
8. [Thread Safety Model](ARCHITECTURE_DIAGRAMS.md#8-thread-safety-model)
9. [Component Dependency Graph](ARCHITECTURE_DIAGRAMS.md#9-component-dependency-graph)
10. [Query Latency Profile](ARCHITECTURE_DIAGRAMS.md#10-query-latency-profile-l2-scale)

---

## 3. **Implementation Status**

### [`PROJECT_STATUS.md`](PROJECT_STATUS.md) — Current State Snapshot
**Best for**: Understanding what's implemented and what's not
- High-level architecture review
- Detailed Layer 3 (OperationalGraph) implementation breakdown
- What exists in the repo
- Layer 3 detailed breakdown (Edge management, deploy tracking, remediation, decay, etc.)
- What is NOT working / incomplete
- Unit tests status
- Validation instructions
- Files summary (added/updated/missing)
- Next steps

**Read this when you**: Need to understand the current state of implementation or plan extensions.

---

## 4. **Getting Started**

### [`README.md`](README.md) — Quickstart Guide
**Best for**: Running the system for the first time
- Project description
- Quickstart commands
- Architecture overview
- Key design decisions
- Running full benchmark
- Environment variables
- Docker setup

**Read this when you**: Want to run the code immediately.

---

### [`TODO.md`](TODO.md) — Roadmap
**Best for**: Understanding incomplete work
- Dashboard implementation checklist
- Required tests and features
- Configuration needs

**Read this when you**: Want to contribute or understand what's left to do.

---

## 5. **Code Reference**

### [`schema.py`](schema.py)
TypedDict definitions for:
- `Event` — Infrastructure event schema
- `CausalEdge` — Causal relationship output
- `SimilarIncident` — Past incident match
- `Remediation` — Action recommendation
- `IncidentSignal` — Incident trigger
- `Context` — Final assembled output

**Use this when**: Writing code that interfaces with the system.

---

## 6. **Testing & Validation**

### [`self_check.py`](self_check.py)
Benchmark suite with 11 aligned checks:
1. Entity Resolution
2. Temporal Causality
3. Confidence Increments
4. Remediation Reinforcement
5. Confidence Decay
6. Graph Traversal
7. Motif Extraction
8. Similar Incident Matching
9. Suggested Remediations
10. Fast Mode Latency
11. Deep Mode Explanation

**Run with**:
```bash
python self_check.py --adapter adapters.engine:Engine --quick
```

---

## 7. **User Interface**

### [`dashboard.py`](dashboard.py)
Streamlit-based interactive dashboard for:
- Live graph visualization
- Statistics and metrics
- Edge inspection
- Remediation history
- Decay simulation
- Test scenarios

**Run with**:
```bash
streamlit run dashboard.py
```

---

## 8. **Code Structure Overview**

```
Mini_Anvil/
├── Documentation (you are here)
│   ├── DOCUMENTATION_INDEX.md      ← This file
│   ├── ANALYSIS_SUMMARY.md         ← Quick reference
│   ├── PROJECT_OVERVIEW.md         ← Complete manual
│   ├── ARCHITECTURE_DIAGRAMS.md    ← Visual guide
│   ├── PROJECT_STATUS.md           ← Implementation snapshot
│   ├── README.md                   ← Quickstart
│   ├── TODO.md                     ← Roadmap
│   └── schema.py                   ← Type definitions
│
├── Source Code
│   ├── adapters/engine.py          ← Main entry point (Engine class)
│   │
│   └── engine/                     ← 4-layer implementation
│       ├── identity.py             ├─ Layer 1: Identity Resolver
│       ├── store.py                ├─ Layer 2: Event Store (DuckDB)
│       ├── graph.py                ├─ Layer 3: Operational Graph
│       ├── assembler.py            ├─ Layer 4: Context Assembler
│       ├── models.py               ├─ Data models
│       └── motifs.py               └─ Motif index
│
├── Testing & Running
│   ├── self_check.py               ← Benchmark suite (11 checks)
│   ├── dashboard.py                ← Streamlit UI
│   ├── streamlit_smoke_check.py    ← Syntax validation
│   └── Dockerfile                  ← Docker build
│
├── Configuration
│   └── requirements.txt             ← Dependencies
│
└── Project Files
    ├── .gitignore
    └── report.json                  ← Benchmark output
```

---

## Navigation Guide by Use Case

### "I want to understand the system quickly"
1. Start: [`ANALYSIS_SUMMARY.md`](ANALYSIS_SUMMARY.md)
2. Then: [`ARCHITECTURE_DIAGRAMS.md`](ARCHITECTURE_DIAGRAMS.md) (visualize)
3. Reference: [`PROJECT_OVERVIEW.md`](PROJECT_OVERVIEW.md) (deep dive)

### "I want to run the code"
1. Start: [`README.md`](README.md) (quickstart)
2. Commands:
   ```bash
   pip install -r requirements.txt
   python self_check.py --adapter adapters.engine:Engine --quick
   streamlit run dashboard.py
   ```

### "I want to understand a specific component"
1. For **Layer 1** (Identity): [`PROJECT_OVERVIEW.md#layer-1`](PROJECT_OVERVIEW.md#layer-1-identity-resolver-engineidentitypy)
2. For **Layer 2** (Events): [`PROJECT_OVERVIEW.md#layer-2`](PROJECT_OVERVIEW.md#layer-2-event-store-enginestonepy)
3. For **Layer 3** (Graph): [`PROJECT_OVERVIEW.md#layer-3`](PROJECT_OVERVIEW.md#layer-3-operational-graph-enginegraphpy)
4. For **Layer 4** (Assembly): [`PROJECT_OVERVIEW.md#layer-4`](PROJECT_OVERVIEW.md#layer-4-context-assembler-engineassemblerpy)
5. Visualize: [`ARCHITECTURE_DIAGRAMS.md`](ARCHITECTURE_DIAGRAMS.md)

### "I want to extend or fix something"
1. Understand current state: [`PROJECT_STATUS.md`](PROJECT_STATUS.md)
2. Find gaps: [`TODO.md`](TODO.md)
3. Review APIs: [`PROJECT_OVERVIEW.md#key-components`](PROJECT_OVERVIEW.md#key-components--apis)
4. Check type signatures: [`schema.py`](schema.py)

### "I want to understand design decisions"
1. Read: [`PROJECT_OVERVIEW.md#design-principles`](PROJECT_OVERVIEW.md#design-principles)
2. Understand rationale: [`README.md#key-design-decisions`](README.md#key-design-decisions)
3. See visual flow: [`ARCHITECTURE_DIAGRAMS.md`](ARCHITECTURE_DIAGRAMS.md)

### "I want to troubleshoot performance"
1. Check latency profile: [`ARCHITECTURE_DIAGRAMS.md#10`](ARCHITECTURE_DIAGRAMS.md#10-query-latency-profile-l2-scale)
2. Review scalability: [`PROJECT_OVERVIEW.md#scalability`](PROJECT_OVERVIEW.md#scalability)
3. Run benchmark: `python self_check.py --adapter adapters.engine:Engine`

---

## Key Concepts Quick Links

| Concept | Documentation |
|---------|---------------|
| **Canonical IDs** | [Design Principle #1](PROJECT_OVERVIEW.md#1-canonical-ids-first) |
| **Temporal Causality** | [Design Principle #2](PROJECT_OVERVIEW.md#2-temporal-causality), [Diagram #4](ARCHITECTURE_DIAGRAMS.md#4-causal-edge-lifecycle) |
| **Confidence Scoring** | [Layer 3](PROJECT_OVERVIEW.md#layer-3-operational-graph-enginegraphpy), [Diagram #7](ARCHITECTURE_DIAGRAMS.md#7-confidence-scoring--decay) |
| **Remediation Reinforcement** | [Layer 3 API](PROJECT_OVERVIEW.md#remediation-reinforcement) |
| **Motif Matching** | [Motif Index](PROJECT_OVERVIEW.md#behavioral-motif-index-enginemotifspy), [Diagram #6](ARCHITECTURE_DIAGRAMS.md#6-motif-extraction--similarity) |
| **Event Store** | [Layer 2](PROJECT_OVERVIEW.md#layer-2-event-store-enginestonepy) |
| **Context Assembly** | [Layer 4](PROJECT_OVERVIEW.md#layer-4-context-assembler-engineassemblerpy), [Diagram #3](ARCHITECTURE_DIAGRAMS.md#3-context-reconstruction-flow) |
| **Thread Safety** | [Design Principle #7](PROJECT_OVERVIEW.md#7-thread-safety), [Diagram #8](ARCHITECTURE_DIAGRAMS.md#8-thread-safety-model) |

---

## API Reference Quick Links

| Component | Signature | Documentation |
|-----------|-----------|----------------|
| **Engine** | `ingest()`, `reconstruct_context()` | [Adapter API](PROJECT_OVERVIEW.md#adapter-adaptersengineepy) |
| **IdentityResolver** | `resolve()`, `rename()`, `current_name()` | [Layer 1 API](PROJECT_OVERVIEW.md#layer-1-identity-resolver-engineidentitypy) |
| **EventStore** | `append()`, `get_window()`, `get_by_trace_ids()` | [Layer 2 API](PROJECT_OVERVIEW.md#layer-2-event-store-enginestonepy) |
| **OperationalGraph** | `add_edge()`, `get_causal_chain()`, `reinforce_remediation()` | [Layer 3 API](PROJECT_OVERVIEW.md#layer-3-operational-graph-enginegraphpy) |
| **ContextAssembler** | `assemble()` | [Layer 4 API](PROJECT_OVERVIEW.md#layer-4-context-assembler-engineassemblerpy) |
| **BehavioralMotifIndex** | `index_incident()`, `find_similar()` | [Motif Index API](PROJECT_OVERVIEW.md#behavioral-motif-index-enginemotifspy) |

---

## Environment Setup

**Environment Variables**:
- `OPENAI_API_KEY` — For GPT-4o-mini deep mode
- `OPENAI_MODEL` — Override model (default: gpt-4o-mini)
- `ANTHROPIC_API_KEY` — For Claude deep mode
- `ANTHROPIC_MODEL` — Override model

**Dependencies**: See [`requirements.txt`](requirements.txt)

**Installation**:
```bash
pip install -r requirements.txt
```

---

## Contributing & Extending

**If you want to**:
- Add tests: See [`PROJECT_STATUS.md#unit-tests-missing`](PROJECT_STATUS.md#41-unit-tests-are-missing)
- Add multi-relation edges: See [`PROJECT_OVERVIEW.md#known-limitations`](PROJECT_OVERVIEW.md#known-limitations)
- Scale to distributed: See [`PROJECT_OVERVIEW.md#future-enhancements`](PROJECT_OVERVIEW.md#future-enhancements)
- Improve dashboard: See [`TODO.md`](TODO.md)

---

## Document Metadata

| Document | Purpose | Length | Best For |
|----------|---------|--------|----------|
| ANALYSIS_SUMMARY.md | Quick reference | ~3 min | Onboarding, overview |
| PROJECT_OVERVIEW.md | Complete manual | ~20 min | Deep understanding, APIs |
| ARCHITECTURE_DIAGRAMS.md | Visual guide | ~10 min | Understanding system flow |
| PROJECT_STATUS.md | Implementation snapshot | ~15 min | Current state, gaps |
| README.md | Quickstart | ~5 min | Getting started |
| TODO.md | Roadmap | ~2 min | Future work |
| DOCUMENTATION_INDEX.md | This guide | ~5 min | Navigation |

---

## Support & Troubleshooting

**For issues with**:
- **Understanding architecture**: Start with ANALYSIS_SUMMARY.md, then ARCHITECTURE_DIAGRAMS.md
- **Specific APIs**: Refer to PROJECT_OVERVIEW.md component sections
- **Current implementation**: Check PROJECT_STATUS.md
- **Limitations**: See PROJECT_OVERVIEW.md "Known Limitations"
- **Performance**: Check ARCHITECTURE_DIAGRAMS.md latency profile

---

## Document Update History

- **Latest**: Based on codebase as of 2026-05-15
- **Coverage**: All 4 layers, 6 main components, 11 benchmark checks
- **Generated**: Comprehensive analysis documentation suite

---

## TL;DR

**Mini Anvil** is a 4-layer incident context engine. Read:
1. [`ANALYSIS_SUMMARY.md`](ANALYSIS_SUMMARY.md) (3 min) for quick understanding
2. [`ARCHITECTURE_DIAGRAMS.md`](ARCHITECTURE_DIAGRAMS.md) (5 min) for visual flow
3. [`PROJECT_OVERVIEW.md`](PROJECT_OVERVIEW.md) (20 min) for complete details

Then run:
```bash
pip install -r requirements.txt
python self_check.py --adapter adapters.engine:Engine --quick
streamlit run dashboard.py
```

---

**Happy exploring! 🚀**
