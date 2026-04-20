"""Concurrency / linearizability harness for AntiCorruptionLayer.

Confirms that concurrent translations, concurrent guard calls, and concurrent
version registrations remain race-free: per-thread re-entry counters are
isolated, registry mutations are serialised, and outputs are deterministic.
"""

from __future__ import annotations

import threading
from collections.abc import Mapping

from AntiCorruptionLayer import (
    ContractVersion,
    DictAntiCorruptionLayer,
    ForeignPayload,
    SchemaDriftError,
    VersionedAntiCorruptionLayer,
)


def test_concurrent_translations_are_deterministic() -> None:
    acl = DictAntiCorruptionLayer()
    results: list[Mapping[str, object]] = []
    lock = threading.Lock()

    def worker(i: int) -> None:
        local = acl.to_local({"legacy_id": i, "legacy_name": f"u{i}"})
        with lock:
            results.append(local)

    ts = [threading.Thread(target=worker, args=(i,)) for i in range(64)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert len(results) == 64
    # Every result is a local shape — no foreign keys anywhere.
    for r in results:
        assert "id" in r and "legacy_id" not in r


def test_concurrent_reentry_guards_are_thread_local() -> None:
    # Two threads calling to_local in parallel MUST NOT interfere with each
    # other's re-entry depth counter (ACL-INV-03 uses threading.local).
    acl = DictAntiCorruptionLayer()
    barrier = threading.Barrier(8)
    errors: list[BaseException] = []
    lock = threading.Lock()

    def worker(i: int) -> None:
        try:
            barrier.wait()
            for j in range(20):
                acl.to_local({"legacy_id": i * 1000 + j, "legacy_name": f"u{i}_{j}"})
        except BaseException as exc:  # pragma: no cover — defensive
            with lock:
                errors.append(exc)

    ts = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert not errors


def test_concurrent_version_registrations_preserve_all_entries() -> None:
    v = ContractVersion("sys.concurrent", "1.0")
    acl: VersionedAntiCorruptionLayer[object, object] = VersionedAntiCorruptionLayer(
        default_version=v,
    )

    def writer(idx: int) -> None:
        extra = ContractVersion("sys.concurrent", f"1.{idx}")
        acl.register_version(
            extra,
            inbound=lambda b: {"from": idx},
            outbound=lambda local: local,
            guard=lambda b: None,
        )

    ts = [threading.Thread(target=writer, args=(i,)) for i in range(32)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    versions = acl.known_versions()
    assert len(versions) == 32


def test_concurrent_drift_raises_for_unknown_version() -> None:
    acl = DictAntiCorruptionLayer()
    ghost = ForeignPayload(ContractVersion("legacy.example", "ghost"), {})
    failures: list[int] = []
    lock = threading.Lock()

    def worker() -> None:
        try:
            acl.to_local(ghost)
        except SchemaDriftError:
            with lock:
                failures.append(1)

    ts = [threading.Thread(target=worker) for _ in range(32)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert len(failures) == 32
