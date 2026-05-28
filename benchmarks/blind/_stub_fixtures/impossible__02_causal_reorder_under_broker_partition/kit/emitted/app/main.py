"""Kit-like causal reorder buffer with broker partition + gap detection."""
from __future__ import annotations

import heapq
import threading
import time

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

app = FastAPI()

GAP_TIMEOUT_MS = 500


class CausalReorderBuffer:
    def __init__(self) -> None:
        self._buffers: dict[str, list] = {}  # agg -> heap of (seq, ts_ms, payload)
        self._next: dict[str, int] = {}      # agg -> next expected seq
        self._delivered: dict[str, list[dict]] = {}
        self._gaps: dict[str, set[int]] = {}
        self._lock = threading.Lock()

    def accept(self, agg: str, seq: int, payload: dict) -> dict:
        buffered_flag = False
        with self._lock:
            self._buffers.setdefault(agg, [])
            self._next.setdefault(agg, 0)
            self._delivered.setdefault(agg, [])
            self._gaps.setdefault(agg, set())
            # If in broker partition, just queue without draining.
            heapq.heappush(
                self._buffers[agg],
                (seq, int(time.monotonic() * 1000), dict(payload)),
            )
            if seq != self._next[agg]:
                buffered_flag = True
            if not _broker.partitioned():
                self._drain(agg)
            return {"buffered": buffered_flag,
                    "delivered_count": len(self._delivered[agg])}

    def _drain(self, agg: str) -> None:
        heap = self._buffers[agg]
        now_ms = int(time.monotonic() * 1000)
        while heap:
            seq, ts, payload = heap[0]
            expected = self._next[agg]
            if seq < expected:
                # already delivered or superseded — drop.
                heapq.heappop(heap)
                continue
            if seq == expected:
                heapq.heappop(heap)
                self._delivered[agg].append({"sequence": seq, "payload": payload})
                self._next[agg] = expected + 1
                continue
            # seq > expected → gap. If oldest buffered waited > GAP_TIMEOUT_MS
            # from the earliest arrival, emit a GapEvent for expected..seq-1.
            oldest_ts = min(e[1] for e in heap)
            if now_ms - oldest_ts >= GAP_TIMEOUT_MS:
                # Mark all missing sequences as gap, skip forward.
                for missing in range(expected, seq):
                    self._gaps[agg].add(missing)
                self._next[agg] = seq
                continue
            break  # still within budget; wait

    def drain_now(self) -> None:
        with self._lock:
            for agg in list(self._buffers):
                self._drain(agg)

    def delivered(self, agg: str) -> list[dict]:
        with self._lock:
            return list(self._delivered.get(agg, []))

    def gaps(self, agg: str) -> list[int]:
        with self._lock:
            return sorted(self._gaps.get(agg, set()))


class Broker:
    def __init__(self) -> None:
        self._partition_until_ms = 0
        self._lock = threading.Lock()

    def partition_for(self, duration_ms: int) -> None:
        with self._lock:
            self._partition_until_ms = int(time.monotonic() * 1000) + duration_ms

    def partitioned(self) -> bool:
        return int(time.monotonic() * 1000) < self._partition_until_ms


_buf = CausalReorderBuffer()
_broker = Broker()


# Background drainer: polls every 50ms so gap-timeouts + post-partition drains happen.
def _background_drainer() -> None:
    while True:
        time.sleep(0.05)
        try:
            _buf.drain_now()
        except Exception:  # noqa: BLE001
            pass


_drainer = threading.Thread(target=_background_drainer, daemon=True)
_drainer.start()


class EventBody(BaseModel):
    aggregate_id: str = Field(min_length=1)
    sequence: int = Field(ge=0)
    payload: dict = {}


class PartitionBody(BaseModel):
    duration_ms: int = Field(ge=0, le=10000)


@app.get("/health")
def health() -> dict:
    return {"ok": True}


@app.post("/events", status_code=202)
def ingest(body: EventBody) -> dict:
    return _buf.accept(body.aggregate_id, body.sequence, body.payload)


@app.get("/delivered/{agg}")
def delivered(agg: str) -> dict:
    return {"events": _buf.delivered(agg)}


@app.get("/gaps/{agg}")
def gaps(agg: str) -> dict:
    return {"gaps": _buf.gaps(agg)}


@app.post("/broker/_partition", status_code=202)
def partition(body: PartitionBody) -> dict:
    _broker.partition_for(body.duration_ms)
    return {"partitioned_for_ms": body.duration_ms}
