"""
Tests for Layer 2: EventStore (engine/store.py)

Covers:
- append() + count()
- get_window() — in-window, out-of-window, boundary, ordering, unknown CID
- get_by_trace_ids() — match, no-match, empty list, multiple IDs
- get_recent_deploy() — within window, latest-of-many, outside window,
                        no deploy, wrong event kind
- append_batch() — bulk insert count + queryability
- get_by_canonical_ids() — multi-CID, window filter, empty CID list
- duplicate event_ids — store is append-only, duplicates are allowed

All timestamps use ISO-8601 with +00:00 timezone offset.
All tests use an in-memory DuckDB instance (:memory:).
"""

import pytest

from engine.store import EventStore


class TestEventStore:
    # ------------------------------------------------------------------ #
    # Fixed reference timestamps                                           #
    # ------------------------------------------------------------------ #

    # anchor = 10:00:00  →  300-second window = [09:55:00, 10:00:00]
    ANCHOR       = "2024-01-01T10:00:00+00:00"
    IN_WINDOW    = "2024-01-01T09:57:00+00:00"   # 3 min before anchor
    AT_ANCHOR    = "2024-01-01T10:00:00+00:00"   # exact anchor edge
    WIN_START    = "2024-01-01T09:55:00+00:00"   # exact window-start edge
    OUT_WINDOW   = "2024-01-01T09:50:00+00:00"   # 10 min before anchor (outside 5-min window)

    # anchor for 600-second deploy window = [09:50:00, 10:00:00]
    DEPLOY_IN    = "2024-01-01T09:55:00+00:00"   # 5 min before anchor  → inside 600 s
    DEPLOY_IN2   = "2024-01-01T09:51:00+00:00"   # 9 min before anchor  → inside 600 s
    DEPLOY_OUT   = "2024-01-01T09:45:00+00:00"   # 15 min before anchor → outside 600 s

    # ------------------------------------------------------------------ #
    # Setup / teardown                                                     #
    # ------------------------------------------------------------------ #

    def setup_method(self):
        self.store = EventStore(":memory:")

    def teardown_method(self):
        self.store.close()

    # ------------------------------------------------------------------ #
    # append() + count()                                                   #
    # ------------------------------------------------------------------ #

    def test_initial_count_is_zero(self):
        assert self.store.count() == 0

    def test_append_increments_count(self):
        self.store.append("evt-1", "cid-a", self.ANCHOR, "log", {"msg": "hello"})
        assert self.store.count() == 1

    def test_append_multiple_increments_count(self):
        for i in range(3):
            self.store.append(f"evt-{i}", "cid-a", self.IN_WINDOW, "log", {"i": i})
        assert self.store.count() == 3

    def test_append_with_trace_id(self):
        self.store.append("evt-1", "cid-a", self.ANCHOR, "log", {"x": 1}, trace_id="tr-1")
        assert self.store.count() == 1

    # ------------------------------------------------------------------ #
    # get_window()                                                         #
    # ------------------------------------------------------------------ #

    def test_get_window_returns_events_within_window(self):
        raw = {"service": "svc-a", "level": "error"}
        self.store.append("evt-1", "cid-a", self.IN_WINDOW, "log", raw)
        result = self.store.get_window("cid-a", self.ANCHOR, window_s=300)
        assert len(result) == 1
        assert result[0]["service"] == "svc-a"

    def test_get_window_excludes_events_before_window(self):
        # OUT_WINDOW is 10 minutes before anchor — outside 5-minute window
        self.store.append("evt-old", "cid-a", self.OUT_WINDOW, "log", {"msg": "stale"})
        result = self.store.get_window("cid-a", self.ANCHOR, window_s=300)
        assert result == []

    def test_get_window_includes_event_at_exact_anchor(self):
        self.store.append("evt-1", "cid-a", self.AT_ANCHOR, "log", {"msg": "at-anchor"})
        result = self.store.get_window("cid-a", self.ANCHOR, window_s=300)
        assert len(result) == 1

    def test_get_window_includes_event_at_window_start_boundary(self):
        # Event at exactly window_start should be included (ts >= window_start)
        self.store.append("evt-boundary", "cid-a", self.WIN_START, "log", {"msg": "boundary"})
        result = self.store.get_window("cid-a", self.ANCHOR, window_s=300)
        assert len(result) == 1

    def test_get_window_returns_empty_for_unknown_cid(self):
        result = self.store.get_window("cid-nobody", self.ANCHOR, window_s=300)
        assert result == []

    def test_get_window_returns_events_ordered_by_ts_asc(self):
        ts_early = "2024-01-01T09:56:00+00:00"
        ts_late  = "2024-01-01T09:59:00+00:00"
        # Insert in reverse order to confirm DB ordering, not insertion order
        self.store.append("evt-late",  "cid-a", ts_late,  "log", {"seq": 2})
        self.store.append("evt-early", "cid-a", ts_early, "log", {"seq": 1})
        result = self.store.get_window("cid-a", self.ANCHOR, window_s=300)
        assert len(result) == 2
        assert result[0]["seq"] == 1
        assert result[1]["seq"] == 2

    def test_get_window_only_returns_matching_cid(self):
        self.store.append("evt-1", "cid-a", self.IN_WINDOW, "log", {"svc": "a"})
        self.store.append("evt-2", "cid-b", self.IN_WINDOW, "log", {"svc": "b"})
        result = self.store.get_window("cid-a", self.ANCHOR, window_s=300)
        assert len(result) == 1
        assert result[0]["svc"] == "a"

    # ------------------------------------------------------------------ #
    # get_by_trace_ids()                                                   #
    # ------------------------------------------------------------------ #

    def test_get_by_trace_ids_returns_matching_events(self):
        self.store.append("evt-1", "cid-a", self.ANCHOR, "log", {"x": 1}, trace_id="tr-abc")
        self.store.append("evt-2", "cid-b", self.ANCHOR, "log", {"x": 2}, trace_id="tr-xyz")
        result = self.store.get_by_trace_ids(["tr-abc"])
        assert len(result) == 1
        assert result[0]["x"] == 1

    def test_get_by_trace_ids_non_matching_returns_empty(self):
        self.store.append("evt-1", "cid-a", self.ANCHOR, "log", {"x": 1}, trace_id="tr-abc")
        result = self.store.get_by_trace_ids(["tr-NOMATCH"])
        assert result == []

    def test_get_by_trace_ids_empty_list_returns_empty(self):
        self.store.append("evt-1", "cid-a", self.ANCHOR, "log", {"x": 1}, trace_id="tr-abc")
        result = self.store.get_by_trace_ids([])
        assert result == []

    def test_get_by_trace_ids_multiple_ids(self):
        self.store.append("evt-1", "cid-a", self.ANCHOR, "log", {"x": 1}, trace_id="tr-1")
        self.store.append("evt-2", "cid-b", self.ANCHOR, "log", {"x": 2}, trace_id="tr-2")
        self.store.append("evt-3", "cid-c", self.ANCHOR, "log", {"x": 3}, trace_id="tr-3")
        result = self.store.get_by_trace_ids(["tr-1", "tr-3"])
        xs = {r["x"] for r in result}
        assert xs == {1, 3}

    def test_get_by_trace_ids_excludes_none_trace_id(self):
        # Event with no trace_id should not be returned when querying by trace
        self.store.append("evt-1", "cid-a", self.ANCHOR, "log", {"x": 1}, trace_id=None)
        result = self.store.get_by_trace_ids(["tr-abc"])
        assert result == []

    # ------------------------------------------------------------------ #
    # get_recent_deploy()                                                  #
    # ------------------------------------------------------------------ #

    def test_get_recent_deploy_within_window(self):
        self.store.append("d-1", "cid-a", self.DEPLOY_IN, "deploy", {"version": "v2.0"})
        result = self.store.get_recent_deploy("cid-a", self.ANCHOR, window_s=600)
        assert result is not None
        assert result["version"] == "v2.0"

    def test_get_recent_deploy_returns_latest_of_multiple(self):
        # DEPLOY_IN2 is older; DEPLOY_IN is more recent — should return DEPLOY_IN
        self.store.append("d-1", "cid-a", self.DEPLOY_IN2, "deploy", {"version": "v1.0"})
        self.store.append("d-2", "cid-a", self.DEPLOY_IN,  "deploy", {"version": "v2.0"})
        result = self.store.get_recent_deploy("cid-a", self.ANCHOR, window_s=600)
        assert result is not None
        assert result["version"] == "v2.0"

    def test_get_recent_deploy_returns_none_outside_window(self):
        # DEPLOY_OUT is 15 min before anchor; 600 s window only covers 10 min
        self.store.append("d-1", "cid-a", self.DEPLOY_OUT, "deploy", {"version": "v1.0"})
        result = self.store.get_recent_deploy("cid-a", self.ANCHOR, window_s=600)
        assert result is None

    def test_get_recent_deploy_returns_none_when_no_events(self):
        result = self.store.get_recent_deploy("cid-nobody", self.ANCHOR, window_s=600)
        assert result is None

    def test_get_recent_deploy_returns_none_when_no_deploy_kind(self):
        # Only a "log" event exists — get_recent_deploy requires kind='deploy'
        self.store.append("e-1", "cid-a", self.DEPLOY_IN, "log", {"msg": "not a deploy"})
        result = self.store.get_recent_deploy("cid-a", self.ANCHOR, window_s=600)
        assert result is None

    def test_get_recent_deploy_ignores_other_event_kinds(self):
        # A 'metric' event should not be treated as a deploy
        self.store.append("e-1", "cid-a", self.DEPLOY_IN, "metric", {"version": "v99"})
        result = self.store.get_recent_deploy("cid-a", self.ANCHOR, window_s=600)
        assert result is None

    # ------------------------------------------------------------------ #
    # append_batch()                                                       #
    # ------------------------------------------------------------------ #

    def test_append_batch_bulk_insert_count(self):
        rows = [
            ("evt-b1", "cid-a", self.IN_WINDOW, "log",    "tr-1", {"n": 1}),
            ("evt-b2", "cid-b", self.IN_WINDOW, "metric", "tr-2", {"n": 2}),
            ("evt-b3", "cid-c", self.IN_WINDOW, "deploy", None,   {"n": 3}),
        ]
        self.store.append_batch(rows)
        assert self.store.count() == 3

    def test_append_batch_events_are_queryable(self):
        rows = [
            ("evt-b1", "cid-batch", self.IN_WINDOW, "log", None, {"payload": "hello-batch"}),
        ]
        self.store.append_batch(rows)
        result = self.store.get_window("cid-batch", self.ANCHOR, window_s=300)
        assert len(result) == 1
        assert result[0]["payload"] == "hello-batch"

    def test_append_batch_mixed_with_single_append(self):
        self.store.append("single-1", "cid-a", self.IN_WINDOW, "log", {"src": "single"})
        rows = [
            ("batch-1", "cid-a", self.IN_WINDOW, "log", None, {"src": "batch"}),
        ]
        self.store.append_batch(rows)
        assert self.store.count() == 2

    # ------------------------------------------------------------------ #
    # get_by_canonical_ids()                                               #
    # ------------------------------------------------------------------ #

    def test_get_by_canonical_ids_multi_id(self):
        self.store.append("e-1", "cid-x", self.IN_WINDOW, "log", {"svc": "x"})
        self.store.append("e-2", "cid-y", self.IN_WINDOW, "log", {"svc": "y"})
        self.store.append("e-3", "cid-z", self.IN_WINDOW, "log", {"svc": "z"})
        result = self.store.get_by_canonical_ids(["cid-x", "cid-y"], self.ANCHOR, window_s=300)
        svcs = {r["svc"] for r in result}
        assert svcs == {"x", "y"}

    def test_get_by_canonical_ids_excludes_out_of_window(self):
        self.store.append("e-1", "cid-x", self.OUT_WINDOW, "log", {"svc": "x"})  # outside
        self.store.append("e-2", "cid-y", self.IN_WINDOW,  "log", {"svc": "y"})  # inside
        result = self.store.get_by_canonical_ids(["cid-x", "cid-y"], self.ANCHOR, window_s=300)
        svcs = {r["svc"] for r in result}
        assert svcs == {"y"}

    def test_get_by_canonical_ids_empty_list_returns_empty(self):
        self.store.append("e-1", "cid-x", self.IN_WINDOW, "log", {"svc": "x"})
        result = self.store.get_by_canonical_ids([], self.ANCHOR, window_s=300)
        assert result == []

    # ------------------------------------------------------------------ #
    # Duplicate event_ids (append-only semantics)                         #
    # ------------------------------------------------------------------ #

    def test_duplicate_event_ids_allowed(self):
        """Store is append-only; it must accept the same event_id twice."""
        self.store.append("dup-evt", "cid-a", self.ANCHOR, "log", {"seq": 1})
        self.store.append("dup-evt", "cid-a", self.ANCHOR, "log", {"seq": 2})
        assert self.store.count() == 2

    def test_duplicate_event_ids_both_queryable(self):
        self.store.append("dup-evt", "cid-a", self.ANCHOR, "log", {"seq": 1})
        self.store.append("dup-evt", "cid-a", self.ANCHOR, "log", {"seq": 2})
        result = self.store.get_window("cid-a", self.ANCHOR, window_s=300)
        seqs = {r["seq"] for r in result}
        assert seqs == {1, 2}
