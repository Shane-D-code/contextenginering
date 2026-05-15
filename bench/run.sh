#!/usr/bin/env bash
# bench/run.sh — Anvil P-02 benchmark runner
#
# Spec requirement: "bench/run.sh ingests the published sample, runs the
# canonical scenario, emits a JSON report matching the SDK schema."
#
# Usage:
#   bash bench/run.sh           # full run
#   bash bench/run.sh --quick   # fast iteration (2 seeds, small dataset)

set -e
cd "$(dirname "$0")/.."

echo "=========================================="
echo " Anvil P-02 — Persistent Context Engine"
echo " Benchmark Runner"
echo "=========================================="

MODE="full"
if [[ "$1" == "--quick" ]]; then
    MODE="quick"
fi

# ---------------------------------------------------------------------------
# STEP 1: Canonical Annex A worked example (L1 validation)
# ---------------------------------------------------------------------------
echo ""
echo "[1/4] Canonical Annex A scenario (L1) ..."

# Write the exact Annex A JSONL sample to a temp file
ANNEX_A_JSONL=$(mktemp /tmp/anvil_annex_a_XXXX.jsonl)
cat > "$ANNEX_A_JSONL" << 'JSONL'
{"ts":"2026-05-10T14:21:30Z","kind":"deploy","service":"payments-svc","version":"v2.14.0","actor":"ci"}
{"ts":"2026-05-10T14:22:01Z","kind":"log","service":"checkout-api","level":"error","msg":"timeout calling payments-svc","trace_id":"abc123"}
{"ts":"2026-05-10T14:22:01Z","kind":"metric","service":"payments-svc","name":"latency_p99_ms","value":4820}
{"ts":"2026-05-10T14:22:08Z","kind":"trace","trace_id":"abc123","spans":[{"svc":"checkout-api","dur_ms":5012},{"svc":"payments-svc","dur_ms":4980}]}
{"ts":"2026-05-10T14:30:00Z","kind":"topology","change":"rename","from":"payments-svc","to":"billing-svc"}
{"ts":"2026-05-10T14:32:11Z","kind":"incident_signal","incident_id":"INC-714","trigger":"alert:checkout-api/error-rate>5%"}
{"ts":"2026-05-10T15:10:00Z","kind":"remediation","incident_id":"INC-714","action":"rollback","target":"billing-svc","version":"v2.13.4","outcome":"resolved"}
JSONL

# Run the L1 canonical scenario via Python and emit JSON
python - << PYEOF
import json, sys, time
sys.path.insert(0, ".")

from adapters.engine import Engine

engine = Engine()

# Ingest the Annex A sample
events = []
with open("$ANNEX_A_JSONL") as f:
    for line in f:
        line = line.strip()
        if line:
            events.append(json.loads(line))

engine.ingest(events)

# Reconstruct context for INC-714 as billing-svc (post-rename)
signal = {
    "service": "billing-svc",
    "ts": "2026-05-10T14:32:11Z",
    "incident_id": "INC-714",
    "trigger": "alert:checkout-api/error-rate>5%",
}

t0 = time.perf_counter()
ctx = engine.reconstruct_context(signal, mode="fast")
latency_ms = (time.perf_counter() - t0) * 1000

report = {
    "scenario": "annex_a_canonical",
    "latency_ms": round(latency_ms, 2),
    "related_events_count": len(ctx.get("related_events", [])),
    "causal_chain_count": len(ctx.get("causal_chain", [])),
    "similar_past_incidents_count": len(ctx.get("similar_past_incidents", [])),
    "suggested_remediations_count": len(ctx.get("suggested_remediations", [])),
    "confidence": ctx.get("confidence", 0.0),
    "explain_length": len(ctx.get("explain", "")),
    "context": ctx,
}

with open("report_annex_a.json", "w") as out:
    json.dump(report, out, indent=2)

# Validate required fields
assert "related_events" in ctx, "FAIL: missing related_events"
assert "causal_chain" in ctx, "FAIL: missing causal_chain"
assert "similar_past_incidents" in ctx, "FAIL: missing similar_past_incidents"
assert "suggested_remediations" in ctx, "FAIL: missing suggested_remediations"
assert "confidence" in ctx, "FAIL: missing confidence"
assert "explain" in ctx and ctx["explain"], "FAIL: missing or empty explain"

print(f"  L1 PASS  latency={latency_ms:.1f}ms  "
      f"related={len(ctx.get('related_events',[]))}  "
      f"causal={len(ctx.get('causal_chain',[]))}  "
      f"similar={len(ctx.get('similar_past_incidents',[]))}  "
      f"remed={len(ctx.get('suggested_remediations',[]))}")
print("  report_annex_a.json written")

engine.close()
PYEOF

rm -f "$ANNEX_A_JSONL"

# ---------------------------------------------------------------------------
# STEP 2: self_check (multi-check battery)
# ---------------------------------------------------------------------------
echo ""
echo "[2/4] Self-check battery ..."
if [[ "$MODE" == "quick" ]]; then
    python self_check.py --adapter adapters.engine:Engine --quick
else
    python self_check.py --adapter adapters.engine:Engine
fi

# ---------------------------------------------------------------------------
# STEP 3: Multi-seed run (L2 property-based)
# ---------------------------------------------------------------------------
echo ""
if [[ "$MODE" == "quick" ]]; then
    echo "[3/4] Multi-seed run (quick: 2 seeds) ..."
    python run.py \
        --adapter adapters.engine:Engine \
        --mode fast \
        --seeds 42 101 \
        --n-services 12 \
        --days 7 \
        --out report_multiseed.json
else
    echo "[3/4] Multi-seed run (5 seeds, L2 defaults) ..."
    python run.py \
        --adapter adapters.engine:Engine \
        --mode fast \
        --seeds 9999 31415 27182 16180 11235 \
        --n-services 12 \
        --days 7 \
        --out report_multiseed.json
fi

# ---------------------------------------------------------------------------
# STEP 4: Unit tests
# ---------------------------------------------------------------------------
echo ""
echo "[4/4] Unit tests ..."
python -m pytest tests/ -q --tb=short

echo ""
echo "=========================================="
echo " Results written:"
echo "   report_annex_a.json   — L1 canonical scenario"
echo "   report.json           — self_check output"
echo "   report_multiseed.json — L2 multi-seed output"
echo "=========================================="
