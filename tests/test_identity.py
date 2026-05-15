"""
Tests for Layer 1: IdentityResolver (engine/identity.py)

Covers:
- register() idempotency and canonical-ID format
- resolve() auto-creation
- rename() forward + chained mappings
- current_name() / all_names() / rename_history()
- to_dict() / from_dict() round-trip serialisation
- thread-safety under concurrent resolve() calls
- current_name() fall-through for unknown IDs
"""

import threading

import pytest

from engine.identity import IdentityResolver


class TestIdentityResolver:
    # ------------------------------------------------------------------ #
    # Setup                                                                #
    # ------------------------------------------------------------------ #

    def setup_method(self):
        self.resolver = IdentityResolver()

    # ------------------------------------------------------------------ #
    # register()                                                           #
    # ------------------------------------------------------------------ #

    def test_register_returns_canonical_id(self):
        cid = self.resolver.register("my-svc")
        assert cid is not None and len(cid) == 8

    def test_register_idempotent(self):
        cid1 = self.resolver.register("svc")
        cid2 = self.resolver.register("svc")
        assert cid1 == cid2

    def test_register_returns_hex_string(self):
        cid = self.resolver.register("hex-check")
        # uuid4().hex[:8] produces exactly 8 lowercase hex characters
        assert all(c in "0123456789abcdef" for c in cid)

    def test_register_different_names_get_different_ids(self):
        cid_a = self.resolver.register("alpha")
        cid_b = self.resolver.register("beta")
        assert cid_a != cid_b

    # ------------------------------------------------------------------ #
    # resolve()                                                            #
    # ------------------------------------------------------------------ #

    def test_resolve_creates_new_entry(self):
        cid = self.resolver.resolve("brand-new")
        assert cid is not None
        assert self.resolver.resolve("brand-new") == cid  # idempotent

    def test_resolve_returns_same_id_as_register(self):
        cid_reg = self.resolver.register("shared")
        cid_res = self.resolver.resolve("shared")
        assert cid_reg == cid_res

    # ------------------------------------------------------------------ #
    # rename()                                                             #
    # ------------------------------------------------------------------ #

    def test_rename_maps_both_names(self):
        cid = self.resolver.register("old")
        self.resolver.rename("old", "new", "2024-01-01T00:00:00Z")
        assert self.resolver.resolve("old") == cid
        assert self.resolver.resolve("new") == cid

    def test_rename_chained(self):
        cid = self.resolver.register("v1")
        self.resolver.rename("v1", "v2", "2024-01-01T00:00:00Z")
        self.resolver.rename("v2", "v3", "2024-01-02T00:00:00Z")
        assert self.resolver.resolve("v1") == cid
        assert self.resolver.resolve("v2") == cid
        assert self.resolver.resolve("v3") == cid

    def test_rename_unknown_source_auto_registers(self):
        # rename() on an unseen old_name should still work (creates it)
        cid = self.resolver.rename("ghost", "ghost-v2", "2024-01-01T00:00:00Z")
        assert cid is not None
        assert self.resolver.resolve("ghost") == cid
        assert self.resolver.resolve("ghost-v2") == cid

    # ------------------------------------------------------------------ #
    # current_name()                                                       #
    # ------------------------------------------------------------------ #

    def test_current_name_returns_latest(self):
        self.resolver.register("first")
        cid = self.resolver.resolve("first")
        self.resolver.rename("first", "second", "T1")
        self.resolver.rename("second", "third", "T2")
        assert self.resolver.current_name(cid) == "third"

    def test_current_name_before_any_rename(self):
        cid = self.resolver.register("only-name")
        assert self.resolver.current_name(cid) == "only-name"

    def test_unknown_canonical_id_returns_itself(self):
        # Fall-through: unknown ID has no names, so return the ID itself
        result = self.resolver.current_name("nonexistent-id")
        assert result == "nonexistent-id"

    # ------------------------------------------------------------------ #
    # all_names()                                                          #
    # ------------------------------------------------------------------ #

    def test_all_names_full_history(self):
        self.resolver.register("a")
        cid = self.resolver.resolve("a")
        self.resolver.rename("a", "b", "T1")
        self.resolver.rename("b", "c", "T2")
        names = set(self.resolver.all_names(cid))
        assert names >= {"a", "b", "c"}

    def test_all_names_single_name(self):
        cid = self.resolver.register("solo")
        names = self.resolver.all_names(cid)
        assert names == ["solo"]

    def test_all_names_unknown_id_returns_empty(self):
        assert self.resolver.all_names("no-such-id") == []

    # ------------------------------------------------------------------ #
    # rename_history()                                                     #
    # ------------------------------------------------------------------ #

    def test_rename_history_records_events(self):
        self.resolver.register("svc")
        cid = self.resolver.resolve("svc")
        self.resolver.rename("svc", "svc-v2", "2024-01-01T00:00:00Z")
        self.resolver.rename("svc-v2", "svc-v3", "2024-01-02T00:00:00Z")
        history = self.resolver.rename_history(cid)
        assert len(history) == 2
        assert history[0].old_name == "svc"
        assert history[0].new_name == "svc-v2"
        assert history[1].old_name == "svc-v2"
        assert history[1].new_name == "svc-v3"

    def test_rename_history_timestamps_preserved(self):
        cid = self.resolver.register("svc")
        self.resolver.rename("svc", "svc-renamed", "2024-06-15T12:00:00Z")
        events = self.resolver.rename_history(cid)
        assert len(events) == 1
        assert events[0].ts == "2024-06-15T12:00:00Z"
        assert events[0].canonical_id == cid

    def test_rename_history_empty_before_renames(self):
        cid = self.resolver.register("no-renames")
        assert self.resolver.rename_history(cid) == []

    def test_rename_history_isolated_per_id(self):
        cid_a = self.resolver.register("a")
        cid_b = self.resolver.register("b")
        self.resolver.rename("a", "a2", "T1")
        # cid_b should have no rename history
        assert self.resolver.rename_history(cid_b) == []
        assert len(self.resolver.rename_history(cid_a)) == 1

    # ------------------------------------------------------------------ #
    # to_dict() / from_dict()                                              #
    # ------------------------------------------------------------------ #

    def test_serialization_roundtrip(self):
        self.resolver.register("svc1")
        self.resolver.rename("svc1", "svc1-renamed", "T1")
        data = self.resolver.to_dict()
        new_resolver = IdentityResolver.from_dict(data)
        cid = new_resolver.resolve("svc1")
        assert new_resolver.resolve("svc1-renamed") == cid
        assert new_resolver.current_name(cid) == "svc1-renamed"

    def test_serialization_preserves_rename_history(self):
        cid = self.resolver.register("orig")
        self.resolver.rename("orig", "renamed", "2024-03-01T00:00:00Z")
        data = self.resolver.to_dict()
        restored = IdentityResolver.from_dict(data)
        history = restored.rename_history(cid)
        assert len(history) == 1
        assert history[0].old_name == "orig"
        assert history[0].new_name == "renamed"

    def test_serialization_preserves_multiple_services(self):
        cid_x = self.resolver.register("svc-x")
        cid_y = self.resolver.register("svc-y")
        data = self.resolver.to_dict()
        restored = IdentityResolver.from_dict(data)
        assert restored.resolve("svc-x") == cid_x
        assert restored.resolve("svc-y") == cid_y

    # ------------------------------------------------------------------ #
    # Thread safety                                                        #
    # ------------------------------------------------------------------ #

    def test_thread_safe_concurrent_resolve(self):
        results = []
        errors = []

        def worker(name):
            try:
                cid = self.resolver.resolve(name)
                results.append(cid)
            except Exception as e:
                errors.append(str(e))

        threads = [
            threading.Thread(target=worker, args=(f"svc-{i}",))
            for i in range(20)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert len(results) == 20

    def test_thread_safe_same_name_concurrent_resolve(self):
        """Concurrent resolves of the same name must all return the same ID."""
        results = []
        barrier = threading.Barrier(10)

        def worker():
            barrier.wait()  # all threads start simultaneously
            results.append(self.resolver.resolve("shared-svc"))

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(set(results)) == 1  # all identical
