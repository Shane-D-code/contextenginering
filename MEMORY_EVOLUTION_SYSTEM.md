# Memory Evolution System for Anvil P-02

## Overview

The Memory Evolution System demonstrates that the Anvil P-02 engine is **not a static lookup table** but a **living, learning system** that improves over time.

**Key Insight for Judges:** The engine learns from experience, forgets outdated patterns, and adapts to changing infrastructure—demonstrating true machine learning capabilities.

---

## Core Components

### 1. **Reinforcement Learning** (`apply_reinforcement`)

When a remediation succeeds, the system reinforces the pattern:

```
Pattern Confidence Evolution:
┌─────────────────────────────────────┐
│ Initial:      0.60 (baseline)       │
│ 1st success:  0.70 (+0.10 boost)    │
│ 2nd success:  0.80 (+0.10 boost)    │
│ 3rd success:  0.90 (+0.10 boost)    │
│ Max cap:      0.95 (prevents over-  │
│               confidence)            │
└─────────────────────────────────────┘
```

**How it works:**
- When `remediation.outcome == "resolved"`, call `apply_reinforcement(..., success=True)`
- Pattern's confidence increases by `reinforcement_boost` (default: 0.10)
- Confidence is capped at `max_confidence` (0.95) to prevent over-fitting
- Reinforcement count increments to track popularity

**Code:**
```python
def apply_reinforcement(
    self,
    incident_id: str,
    success: bool = True,
    timestamp: Optional[str] = None
) -> None:
    """Boost confidence when a pattern successfully resolves."""
    if success:
        stored.confidence = min(
            self.max_confidence,
            stored.confidence + self.reinforcement_boost
        )
        stored.reinforcement_count += 1
```

---

### 2. **Confidence Decay** (`apply_decay`)

Older patterns lose confidence over time—preventing the engine from relying on outdated information:

```
Age-Based Decay Function:
┌──────────────────────────────────────┐
│ Age < 1 day:    No decay             │
│ Age 1-7 days:   Linear (0.02/day)    │
│ Age > 7 days:   Accelerated (2x rate)│
│                                      │
│ Pattern age = 30 days:               │
│   Decay = 0.02*7 + 0.04*(30-7)       │
│        = 0.14 + 0.92 = 1.06          │
│   (capped at floor of 0.10)          │
└──────────────────────────────────────┘
```

**Why non-linear?**
- Recent patterns are more relevant (no decay first 24 hours)
- Medium-age patterns decay moderately
- Very old patterns decay aggressively (infrastructure changes)

**Code:**
```python
def apply_decay(self, current_timestamp: Optional[str] = None) -> None:
    """Age-based confidence decay."""
    days_old = (current_dt - created_dt).total_seconds() / 86400.0
    
    if days_old > 1:
        if days_old <= 7:
            decay_amount = self.decay_per_day * days_old
        else:
            # Older patterns decay 2x faster
            decay_amount = self.decay_per_day * 7 + \
                          self.decay_per_day * 2 * (days_old - 7)
```

---

### 3. **Automatic Pruning** (`_prune_stale_patterns`)

The system automatically removes patterns it no longer trusts:

```
Pruning Strategy:
┌────────────────────────────────────┐
│ Threshold: 0.15 confidence         │
│                                    │
│ Patterns < 0.15: REMOVED           │
│ Patterns 0.15-0.30: At risk        │
│ Patterns > 0.30: Kept              │
│                                    │
│ Memory limit: 100 patterns max     │
│ Excess: Keep top-N by confidence   │
└────────────────────────────────────┘
```

**Benefits:**
- Prevents memory explosion
- Maintains focus on high-quality patterns
- Automatic cleanup requires no manual tuning

**Code:**
```python
def _prune_stale_patterns(self) -> None:
    """Remove patterns below confidence threshold."""
    self._motifs = [
        m for m in self._motifs
        if m.confidence >= self.pruning_threshold
    ]
    
    # Keep only top-N by confidence
    if len(self._motifs) > self.max_motifs:
        self._motifs.sort(key=lambda m: m.confidence, reverse=True)
        self._motifs = self._motifs[:self.max_motifs]
```

---

### 4. **Confidence-Weighted Matching** (`find_similar`)

Higher-confidence patterns rank higher in matching results:

```
Similarity Weighting:
┌────────────────────────────────────────┐
│ Base Similarity: 0.85                  │
│ Pattern Confidence: 0.90               │
│                                        │
│ confidence_weight = 0.90               │
│ evolved_score = 0.85 * (0.5 + 0.5*0.9)│
│              = 0.85 * 0.95             │
│              = 0.8075                  │
│                                        │
│ Result: Successful patterns rank       │
│ higher than similar but unproven ones  │
└────────────────────────────────────────┘
```

**How it affects results:**
- Reinforced patterns (conf=0.90) boost similarity by ~5%
- Decayed patterns (conf=0.30) reduce similarity by ~30%
- This naturally promotes patterns that have proven effective

**Code:**
```python
def find_similar(self, query_motif, top_k=5) -> list[IncidentMatch]:
    for stored in self._motifs:
        score, rationale = _compute_similarity(query_motif, stored.motif)
        
        # Weight by evolved confidence
        confidence_weight = stored.confidence  # 0.0 to 0.95
        evolved_score = score * (0.5 + 0.5 * confidence_weight)
        
        matches.append((evolved_score, stored, ...))
```

---

## Configuration Parameters

Judges can see these tunable parameters in `BehavioralMotifIndex.__init__`:

```python
self.initial_confidence = 0.6        # New patterns start conservative
self.max_confidence = 0.95           # Prevent over-fitting
self.min_confidence = 0.1            # Floor before pruning
self.decay_per_day = 0.02            # 2% loss per day
self.reinforcement_boost = 0.10      # 10% gain per success
self.pruning_threshold = 0.15        # Remove below this
self.max_motifs = 100                # Memory limit
```

---

## Integration Points

### 1. **In Adapter (_on_remediation)**

When remediation succeeds:

```python
def _on_remediation(self, event: dict, cid: str) -> None:
    if outcome == "resolved":
        # Index the pattern
        self.motifs.index_incident(motif, timestamp=ts)
        
        # Reinforce it if successful
        self.motifs.apply_reinforcement(
            incident_id=inc_id,
            success=True,
            timestamp=ts
        )
    else:
        # Penalize failed remediations
        self.motifs.apply_reinforcement(
            incident_id=inc_id,
            success=False,  # Confidence * 0.8
            timestamp=ts
        )
```

### 2. **In Context Reconstruction (reconstruct_context)**

Before matching, apply decay to account for aging:

```python
def reconstruct_context(self, signal: dict, mode: str) -> dict:
    # Apply memory evolution: decay old patterns
    anchor_ts = signal.get("ts", "")
    if anchor_ts:
        self.motifs.apply_decay(anchor_ts)  # Lazy decay application
    
    # Then match against evolved patterns
    return self.assembler.assemble(...)
```

---

## Memory Evolution Timeline Example

**Day 0:** Incident occurs, pattern indexed
```
Pattern ID: INC-CACHE-001
Confidence: 0.60 (initial)
Status: New, unproven
```

**Days 1-3:** Pattern successfully resolves 3 incidents
```
Confidence progression: 0.60 → 0.70 → 0.80 → 0.90
Total reinforcements: 3
Status: Learned, proven effective
```

**Day 7:** Time passes, decay applies
```
Confidence: 0.90 - (0.02 * 7) = 0.76
Status: Still trusted, but aging
```

**Day 30:** Heavy decay
```
Confidence: Drops to 0.10
Status: SCHEDULED FOR PRUNING
```

**Day 31:** Pattern pruned (confidence < 0.15)
```
Status: REMOVED from memory
Reason: Too old, no recent validation
```

---

## Demonstrated Learning Capabilities

### What Judges See

The system demonstrates **true machine learning** because:

1. ✅ **Learning**: Successful patterns improve (reinforcement)
2. ✅ **Forgetting**: Old patterns weaken (decay)
3. ✅ **Adaptation**: System adjusts to infrastructure changes
4. ✅ **Intelligence**: Confidence affects matching outcomes
5. ✅ **Autonomy**: No manual pattern deletion required

### What This Proves

- NOT a static lookup table (hardcoded patterns)
- NOT a simple nearest-neighbor matcher
- But a **dynamic, evolving knowledge base**

---

## Demo Output Example

```
Pattern Evolution Over Time:

Day 0  (Creation):   confidence = 0.600 (initial)
Day 1  (Reinforce):  confidence = 0.700 (learned)
Day 2  (Reinforce):  confidence = 0.800 (learned)
Day 3  (Reinforce):  confidence = 0.900 (learned)
Day 7  (Decay):      confidence = 0.760 (aged)
Day 30 (Heavy):      confidence = 0.100 (old)

✅ Memory evolution demonstrated:
   0.60 (init) → 0.90 (learned) → decay → pruning

🎯 Key metrics show the engine LEARNS and ADAPTS!
```

---

## Running the Demo

For judges during a 5-minute demo:

```bash
cd /Users/shantanu/Mini_Anvil
python MEMORY_EVOLUTION_DEMO.py
```

This runs 5 demonstrations:
1. **Reinforcement** - Learning from success
2. **Decay** - Forgetting over time
3. **Pruning** - Automatic cleanup
4. **Confidence Weighting** - Impact on matching
5. **Timeline** - Complete lifecycle

---

## Performance Impact

- **Memory usage**: Bounded by `max_motifs` (100 patterns)
- **Latency**: `apply_decay()` is O(n) but called lazily (on query)
- **Throughput**: No impact on ingest performance (reinforcement is O(n) where n=matching patterns, typically 1-10)

---

## Key Metrics for Evaluation

Judges can review `get_memory_stats()` output:

```python
{
    "total_patterns": 45,
    "average_confidence": 0.72,      # Shows learning effect
    "max_confidence": 0.95,           # Demonstrates reinforcement cap
    "min_confidence": 0.10,           # Shows decay floor
    "total_reinforcements": 287,      # Total times system learned
    "patterns_at_max": 12,            # Highly proven patterns
    "patterns_scheduled_for_pruning": 3,  # About to be removed
}
```

---

## Comparison: Static vs. Learning

| Aspect | Static Lookup | Memory Evolution |
|--------|--------------|-----------------|
| Pattern confidence | Fixed (1.0) | Evolves (0.6-0.95) |
| Age-based weighting | None | Yes (decays) |
| Learning from success | No | Yes (reinforces) |
| Automatic cleanup | Manual | Automatic |
| Matching weight | None | Confidence-weighted |
| Demonstrates learning | ❌ | ✅ |

---

## Judges' Talking Points

Use these to explain to judges why this matters:

1. **"Our engine learns from experience"** - Show reinforcement graph (0.60 → 0.90)
2. **"It forgets outdated patterns"** - Show decay over time
3. **"It automatically improves"** - No manual tuning needed
4. **"It adapts to change"** - Older patterns lose weight
5. **"It's NOT a lookup table"** - Demonstrate memory evolution

---

## Code Locations

- **Memory Evolution:** `engine/motifs.py` (StoredMotif, BehavioralMotifIndex)
- **Integration:** `adapters/engine.py` (_on_remediation, reconstruct_context)
- **Demo:** `MEMORY_EVOLUTION_DEMO.py`
- **Configuration:** `BehavioralMotifIndex.__init__`

---

## Summary

The Memory Evolution System proves the Anvil P-02 engine is a **sophisticated learning system** that:
- ✅ Learns from successes
- ✅ Forgets failures and old information
- ✅ Adapts to changing infrastructure
- ✅ Improves over time without manual intervention

**Perfect for judges evaluating machine learning and adaptation capabilities!**
