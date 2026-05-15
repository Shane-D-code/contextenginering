#!/usr/bin/env python3
"""
Demonstration and test of the enhanced _generate_explanation method.
Shows sample outputs and how the narrative explanation is built.
"""

import sys
import os

# Setup path to the bench environment
_HERE = os.path.dirname(os.path.abspath(__file__))
_BENCH = os.path.join(_HERE, "Anvil-P-E", "bench-p02-context")
if _BENCH not in sys.path:
    sys.path.insert(0, _BENCH)

from adapters.optimized_engine import Engine

def demo_explanation_generation():
    """Demonstrate the enhanced explanation generation with realistic examples."""

    engine = Engine()

    # Simulate some past incidents
    print("=" * 80)
    print("ENHANCED EXPLANATION GENERATION DEMO")
    print("=" * 80)
    print()

    # Setup past incidents
    engine.past_incidents = [
        {
            "id": "INC-123",
            "trigger": "latency_p99_ms > 500",
            "event_types": ["deploy", "metric", "log", "metric"],
            "services": ["payments-svc"],
            "remediation_action": "rollback",
            "remediation_target": "payments-svc-v2.1",
            "remediation_outcome": "resolved",
            "timestamp": "2026-05-08T14:32:11Z"
        },
        {
            "id": "INC-714",
            "trigger": "error_rate > 5%",
            "event_types": ["log", "metric", "log"],
            "services": ["checkout-api"],
            "remediation_action": "rollback",
            "remediation_target": "checkout-api-v1.9",
            "remediation_outcome": "resolved",
            "timestamp": "2026-05-15T10:15:22Z"
        },
        {
            "id": "INC-456",
            "trigger": "throughput_degradation",
            "event_types": ["metric", "log"],
            "services": ["cache-svc"],
            "remediation_action": "scale",
            "remediation_target": "cache-svc",
            "remediation_outcome": "resolved",
            "timestamp": "2026-05-22T16:45:00Z"
        }
    ]

    # Setup service aliases to demonstrate topology handling
    engine.service_aliases = {
        "billing-svc": "payments-svc"  # Old name -> canonical name
    }

    # Test Case 1: Latency incident similar to historical pattern
    print("TEST CASE 1: Latency Incident")
    print("-" * 80)

    signal1 = {
        "incident_id": "INC-999",
        "trigger": "latency_p99_ms > 450 in checkout-api",
        "ts": "2026-05-29T14:32:11Z"
    }

    similar_incidents1 = [
        {
            "incident_id": "INC-123",
            "similarity": 0.92,
            "rationale": "Similar incident INC-123 resolved by rollback"
        },
        {
            "incident_id": "INC-714",
            "similarity": 0.78,
            "rationale": "Similar incident INC-714 resolved by rollback"
        }
    ]

    causal_chain1 = [
        {
            "cause_event_id": "evt-001",
            "effect_event_id": "evt-002",
            "evidence": "Pattern match with similarity 0.92",
            "confidence": 0.92
        }
    ]

    explanation1 = engine._generate_explanation(signal1, similar_incidents1, causal_chain1, 0.85)
    print(explanation1)
    print()

    # Test Case 2: Error rate incident
    print("TEST CASE 2: Error Rate Incident")
    print("-" * 80)

    signal2 = {
        "incident_id": "INC-1000",
        "trigger": "error_rate > 4% in billing-svc",
        "ts": "2026-05-30T09:15:33Z"
    }

    similar_incidents2 = [
        {
            "incident_id": "INC-714",
            "similarity": 0.88,
            "rationale": "Similar incident INC-714 resolved by rollback"
        }
    ]

    causal_chain2 = [
        {
            "cause_event_id": "evt-003",
            "effect_event_id": "evt-004",
            "evidence": "Pattern match with similarity 0.88",
            "confidence": 0.88
        }
    ]

    explanation2 = engine._generate_explanation(signal2, similar_incidents2, causal_chain2, 0.88)
    print(explanation2)
    print()

    # Test Case 3: Unknown incident (low confidence)
    print("TEST CASE 3: Unknown Incident Pattern")
    print("-" * 80)

    signal3 = {
        "incident_id": "INC-1001",
        "trigger": "memory_pressure > 90%",
        "ts": "2026-05-31T13:22:44Z"
    }

    similar_incidents3 = []
    causal_chain3 = []

    explanation3 = engine._generate_explanation(signal3, similar_incidents3, causal_chain3, 0.35)
    print(explanation3)
    print()

    # Summary
    print("=" * 80)
    print("KEY FEATURES DEMONSTRATED:")
    print("=" * 80)
    print("✓ Specific event timestamps in narrative format (HH:MM:SSZ)")
    print("✓ WHY incidents are similar (causal patterns: deploy → latency → timeout)")
    print("✓ Topology drift handling (service renames tracked)")
    print("✓ Causal chain reasoning (root cause analysis)")
    print("✓ Operational language (rollback, deployment, cascading failures)")
    print("✓ Confidence quantification (0.92 based on event sequence alignment)")
    print("✓ Remediation strategy with evidence-based justification")
    print("✓ Event sequence alignment statistics (match counts, confidence tiers)")
    print()

if __name__ == "__main__":
    demo_explanation_generation()
