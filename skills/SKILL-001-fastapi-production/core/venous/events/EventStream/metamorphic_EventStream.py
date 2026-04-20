"""Metamorphic + differential tests for EventStream.

Algebraic properties:
- Deterministic replica: two EventStream instances receiving the same append
  sequence produce byte-identical per-partition logs.
- read_from is idempotent: two calls at the same offset yield equal snapshots.
- tail() equals last-seq + 1 AND equals len(log_snapshot) + truncated_before.
- truncate_before is monotonic and commutes under the retention floor:
  truncating to a, then b (>= a) is equivalent to truncating to b directly.
- Partition isolation: appends to partition P do not change partition-size or
  tail of any other partition.
"""

from __future__ import annotations

from EventStream import InMemoryEventStream


def test_metamorphic_replica_byte_identical_logs() -> None:
    a = InMemoryEventStream()
    b = InMemoryEventStream()
    for (k, v) in [("p", 1), ("q", 1), ("p", 2), ("q", 2), ("p", 3)]:
        a.append(k, {"v": v})
        b.append(k, {"v": v})
    for key in ("p", "q"):
        la = [(e["seq"], e["event"]) for e in a.log_snapshot(key)]
        lb = [(e["seq"], e["event"]) for e in b.log_snapshot(key)]
        assert la == lb


def test_metamorphic_read_from_idempotent() -> None:
    es = InMemoryEventStream()
    for i in range(7):
        es.append("p", {"i": i})
    assert list(es.read_from("p", 0)) == list(es.read_from("p", 0))
    assert list(es.read_from("p", 4)) == list(es.read_from("p", 4))


def test_metamorphic_tail_equals_last_seq_plus_one() -> None:
    es = InMemoryEventStream()
    for i in range(5):
        es.append("p", {"i": i})
    snap = es.log_snapshot("p")
    last_seq = max(int(e["seq"]) for e in snap)  # type: ignore[arg-type]
    assert es.tail("p") == last_seq + 1
    # Empty partition: tail() is 1 (next seq to assign).
    assert es.tail("never-written") == 1


def test_metamorphic_truncate_composition_equivalence() -> None:
    # Composition of monotonic truncations is a single truncation to the max.
    a = InMemoryEventStream(retention_min_entries=0)
    b = InMemoryEventStream(retention_min_entries=0)
    for i in range(10):
        a.append("p", {"i": i})
        b.append("p", {"i": i})
    a.truncate_before(3)
    a.truncate_before(6)
    b.truncate_before(6)
    la = [(e["seq"], e["event"]) for e in a.log_snapshot("p")]
    lb = [(e["seq"], e["event"]) for e in b.log_snapshot("p")]
    assert la == lb
    assert a.truncated_before_of("p") == b.truncated_before_of("p") == 6


def test_metamorphic_partition_isolation() -> None:
    es = InMemoryEventStream()
    for i in range(4):
        es.append("P", {"i": i})
    tail_p = es.tail("P")
    size_p = es.partition_size("P")
    # Append to an unrelated partition — P is untouched.
    for i in range(5):
        es.append("Q", {"i": i})
    assert es.tail("P") == tail_p
    assert es.partition_size("P") == size_p


def test_metamorphic_seq_contiguous_per_partition() -> None:
    es = InMemoryEventStream()
    for i in range(20):
        es.append("p", {"i": i})
    seqs = [int(e["seq"]) for e in es.log_snapshot("p")]  # type: ignore[arg-type]
    assert seqs == list(range(1, 21))


def test_differential_append_count_equals_tail_minus_one_when_no_truncation() -> None:
    es = InMemoryEventStream()
    N = 15
    for i in range(N):
        es.append("p", {"i": i})
    assert es.tail("p") - 1 == N
    assert es.partition_size("p") == N


def test_metamorphic_truncate_preserves_suffix_order() -> None:
    # Truncation removes a prefix but leaves the suffix byte-identical.
    es = InMemoryEventStream(retention_min_entries=0)
    for i in range(10):
        es.append("p", {"i": i})
    before_suffix = [
        (e["seq"], e["event"]) for e in es.log_snapshot("p") if int(e["seq"]) >= 6  # type: ignore[arg-type]
    ]
    es.truncate_before(6)
    after_suffix = [(e["seq"], e["event"]) for e in es.log_snapshot("p")]
    assert after_suffix == before_suffix
