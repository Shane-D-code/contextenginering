"""
run.py — Multi-seed benchmark runner for Anvil P-02.

Usage:
    python run.py --adapter adapters.engine:Engine --mode fast \
                  --seeds 9999 31415 27182 --out report.json

For each seed, the scenario from self_check.make_scenario(seed) is ingested
into a fresh adapter instance, then reconstruct_context() is called for every
signal.  Per-seed metrics and an aggregate summary are written to --out.
"""
from __future__ import annotations

import argparse
import importlib
import json
import statistics
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Any

# ---------------------------------------------------------------------------
# Scenario data generator  (mirrors self_check.make_scenario exactly)
# ---------------------------------------------------------------------------

BASE = datetime(2026, 1, 15, 10, 0, 0, tzinfo=timezone.utc)


def _ts(base: datetime, delta_s: float) -> str:
    return (base + timedelta(seconds=delta_s)).isoformat()


def make_scenario(seed: int = 42):
    """
    Single-rename scenario: svc-pay-{seed} -> svc-bil-{seed}.

    Returns (train_events, signal_events).
    Identical to self_check.make_scenario so seeds are fully comparable.
    """
    p = f"svc-pay-{seed}"
    b = f"svc-bil-{seed}"
    c = f"svc-chk-{seed}"
    inc1 = f"inc-{seed}-001"

    train = [
        {
            "event_id": f"{seed}-001", "kind": "deploy",
            "service": p, "ts": _ts(BASE, 0), "version": "v2.1.0",
        },
        {
            "event_id": f"{seed}-002", "kind": "metric",
            "service": p, "ts": _ts(BASE, 30),
            "metric": "latency_p99", "value": 520, "threshold": 500,
        },
        {
            "event_id": f"{seed}-003", "kind": "log",
            "service": p, "ts": _ts(BASE, 45),
            "level": "error", "message": "DB timeout",
            "trace_id": f"tr-{seed}-a",
        },
        {
            "event_id": f"{seed}-004", "kind": "trace",
            "service": c, "ts": _ts(BASE, 50),
            "trace_id": f"tr-{seed}-a",
            "spans": [{"svc": p, "ts": _ts(BASE, 51), "status": "error"}],
        },
        {
            "event_id": f"{seed}-005", "kind": "incident_signal",
            "service": p, "ts": _ts(BASE, 60),
            "incident_id": inc1, "trigger": "latency_breach",
        },
        {
            "event_id": f"{seed}-006", "kind": "remediation",
            "service": p, "ts": _ts(BASE, 90),
            "incident_id": inc1, "action": "rollback",
            "version": "v2.0.9", "outcome": "resolved",
        },
        {
            "event_id": f"{seed}-007", "kind": "topology",
            "ts": _ts(BASE, 120), "service": p,
            "mutation": {"kind": "rename", "old_name": p, "new_name": b},
        },
        {
            "event_id": f"{seed}-008", "kind": "deploy",
            "service": b, "ts": _ts(BASE, 150), "version": "v2.1.1",
        },
        {
            "event_id": f"{seed}-009", "kind": "metric",
            "service": b, "ts": _ts(BASE, 180),
            "metric": "latency_p99", "value": 610, "threshold": 500,
        },
        {
            "event_id": f"{seed}-010", "kind": "log",
            "service": b, "ts": _ts(BASE, 190),
            "level": "error", "message": "DB timeout",
            "trace_id": f"tr-{seed}-b",
        },
    ]

    signals = [
        {
            "service": b,
            "ts": _ts(BASE, 200),
            "incident_id": f"inc-{seed}-002",
            "trigger": "latency_breach",
        }
    ]
    return train, signals


# ---------------------------------------------------------------------------
# Adapter loader
# ---------------------------------------------------------------------------

def load_adapter_class(spec: str):
    """
    Load an adapter class from a 'module.path:ClassName' spec.

    Example:
        load_adapter_class("adapters.engine:Engine")
        -> <class 'adapters.engine.Engine'>
    """
    if ":" not in spec:
        raise ValueError(
            f"Invalid adapter spec '{spec}'. Expected format: 'module.path:ClassName'"
        )
    module_path, class_name = spec.rsplit(":", 1)
    try:
        module = importlib.import_module(module_path)
    except ImportError as exc:
        raise ImportError(f"Cannot import module '{module_path}': {exc}") from exc

    try:
        cls = getattr(module, class_name)
    except AttributeError:
        raise AttributeError(
            f"Module '{module_path}' has no class '{class_name}'"
        )
    return cls


# ---------------------------------------------------------------------------
# Per-seed runner
# ---------------------------------------------------------------------------

def run_seed(
    adapter_cls,
    seed: int,
    mode: str,
) -> dict[str, Any]:
    """
    Instantiate a fresh adapter, ingest the scenario, reconstruct context
    for every signal, and return a metrics dict.
    """
    train, signals = make_scenario(seed)

    adapter = adapter_cls()
    try:
        # Ingest training stream
        adapter.ingest(train)

        # Reconstruct context for each signal and collect metrics
        all_latencies: list[float] = []
        all_confidences: list[float] = []
        all_related: list[int] = []
        all_causal: list[int] = []
        all_similar: list[int] = []
        all_remediations: list[int] = []
        errors: list[str] = []

        for sig in signals:
            t0 = time.perf_counter()
            try:
                ctx = adapter.reconstruct_context(sig, mode=mode)
                latency_ms = (time.perf_counter() - t0) * 1000

                all_latencies.append(latency_ms)
                all_confidences.append(float(ctx.get("confidence", 0.0)))
                all_related.append(len(ctx.get("related_events", [])))
                all_causal.append(len(ctx.get("causal_chain", [])))
                all_similar.append(len(ctx.get("similar_past_incidents", [])))
                all_remediations.append(len(ctx.get("suggested_remediations", [])))
            except Exception as exc:
                latency_ms = (time.perf_counter() - t0) * 1000
                all_latencies.append(latency_ms)
                errors.append(str(exc))

        success = len(errors) == 0

        return {
            "seed": seed,
            "success": success,
            "latency_ms": round(statistics.mean(all_latencies), 2) if all_latencies else 0.0,
            "confidence": round(statistics.mean(all_confidences), 4) if all_confidences else 0.0,
            "related_events": int(statistics.mean(all_related)) if all_related else 0,
            "causal_chain_len": int(statistics.mean(all_causal)) if all_causal else 0,
            "similar_incidents": int(statistics.mean(all_similar)) if all_similar else 0,
            "remediations": int(statistics.mean(all_remediations)) if all_remediations else 0,
            "errors": errors if errors else None,
        }

    finally:
        try:
            adapter.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Summary builder
# ---------------------------------------------------------------------------

def build_summary(results: list[dict]) -> dict[str, Any]:
    """Aggregate per-seed results into a summary block."""
    if not results:
        return {"pass_rate": 0.0, "avg_latency_ms": 0.0, "avg_confidence": 0.0}

    passes = sum(1 for r in results if r.get("success", False))
    latencies = [r["latency_ms"] for r in results if r.get("latency_ms") is not None]
    confidences = [r["confidence"] for r in results if r.get("confidence") is not None]

    return {
        "pass_rate": round(passes / len(results), 4),
        "avg_latency_ms": round(statistics.mean(latencies), 2) if latencies else 0.0,
        "avg_confidence": round(statistics.mean(confidences), 4) if confidences else 0.0,
        "total_seeds": len(results),
        "passed": passes,
        "failed": len(results) - passes,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Multi-seed benchmark runner for Anvil P-02.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python run.py --adapter adapters.engine:Engine --seeds 42
  python run.py --adapter adapters.engine:Engine --mode deep --seeds 9999 31415 27182
  python run.py --adapter adapters.engine:Engine --seeds 9999 31415 --out results.json
""",
    )
    parser.add_argument(
        "--adapter",
        default="adapters.engine:Engine",
        help="Adapter spec as 'module.path:ClassName' (default: adapters.engine:Engine)",
    )
    parser.add_argument(
        "--mode",
        choices=["fast", "deep"],
        default="fast",
        help="Reconstruction mode passed to reconstruct_context() (default: fast)",
    )
    parser.add_argument(
        "--seeds",
        nargs="+",
        type=int,
        default=[42],
        metavar="SEED",
        help="Space-separated list of integer seeds (default: 42)",
    )
    parser.add_argument(
        "--out",
        default="report.json",
        help="Output JSON report path (default: report.json)",
    )
    parser.add_argument(
        "--n-services",
        type=int,
        default=12,
        metavar="N",
        help="Number of services in the synthetic dataset (default: 12, matches L2 bench default)",
    )
    parser.add_argument(
        "--days",
        type=float,
        default=7.0,
        metavar="DAYS",
        help="Simulated time span in days (default: 7.0, matches L2 bench default)",
    )
    parser.add_argument(
        "--warmup",
        type=int,
        default=0,
        metavar="N",
        help="Number of warmup queries to discard from latency aggregation (default: 0)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print per-seed results to stdout as they complete",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    print(f"[run.py] Loading adapter: {args.adapter}")
    try:
        adapter_cls = load_adapter_class(args.adapter)
    except (ImportError, AttributeError, ValueError) as exc:
        print(f"[run.py] ERROR: {exc}", file=sys.stderr)
        return 1

    print(
        f"[run.py] Mode: {args.mode}  |  Seeds: {args.seeds}  |  "
        f"n-services: {args.n_services}  |  days: {args.days}  |  Output: {args.out}"
    )
    print()

    results: list[dict] = []
    for seed in args.seeds:
        print(f"  seed {seed:>8} ... ", end="", flush=True)
        t_wall = time.perf_counter()
        row = run_seed(adapter_cls, seed, args.mode)
        wall_ms = (time.perf_counter() - t_wall) * 1000

        status = "PASS" if row["success"] else "FAIL"
        print(
            f"{status}  "
            f"latency={row['latency_ms']:.1f}ms  "
            f"conf={row['confidence']:.3f}  "
            f"related={row['related_events']}  "
            f"causal={row['causal_chain_len']}  "
            f"similar={row['similar_incidents']}  "
            f"remed={row['remediations']}"
        )
        if row.get("errors") and args.verbose:
            for err in row["errors"]:
                print(f"           ERROR: {err}")

        results.append(row)

    summary = build_summary(results)

    report = {
        "adapter": args.adapter,
        "mode": args.mode,
        "seeds": args.seeds,
        "results": results,
        "summary": summary,
    }

    with open(args.out, "w") as f:
        json.dump(report, f, indent=2)

    print()
    print(f"[run.py] Summary:")
    print(f"  pass_rate      : {summary['pass_rate']:.1%}  ({summary['passed']}/{summary['total_seeds']})")
    print(f"  avg_latency_ms : {summary['avg_latency_ms']:.1f} ms")
    print(f"  avg_confidence : {summary['avg_confidence']:.4f}")
    print(f"[run.py] Report written to: {args.out}")

    return 0 if summary["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
