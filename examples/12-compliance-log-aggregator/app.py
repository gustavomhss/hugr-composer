"""Compliance log aggregator — PII tagging, hash-chain, class retention."""
from __future__ import annotations

import hashlib
import json
import re
import threading
from dataclasses import dataclass, field
from typing import Literal


Sensitivity = Literal["general", "pii", "pci", "health"]


CC_RE = re.compile(r"\b(?:\d[ -]?){13,19}\b")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")


def classify_and_mask(fields: dict[str, str]) -> tuple[Sensitivity, dict[str, str]]:
    out = dict(fields)
    sensitivity: Sensitivity = "general"
    # PCI takes precedence (higher sensitivity wins).
    for k, v in list(out.items()):
        if isinstance(v, str) and CC_RE.search(v):
            out[k] = CC_RE.sub("****-MASKED-****", v)
            sensitivity = "pci"
    if sensitivity == "general":
        for k, v in list(out.items()):
            if isinstance(v, str) and (EMAIL_RE.search(v) or SSN_RE.search(v)):
                out[k] = EMAIL_RE.sub("***@***", SSN_RE.sub("***-**-****", v))
                sensitivity = "pii"
    return sensitivity, out


@dataclass(frozen=True)
class LogEntry:
    index: int
    source: str
    timestamp: float
    sensitivity: Sensitivity
    fields: dict
    prev_hash: str
    this_hash: str


def _hash(prev: str, payload: dict) -> str:
    return hashlib.sha256(
        prev.encode() + b"|" + json.dumps(payload, sort_keys=True).encode()
    ).hexdigest()


class LogStore:
    GENESIS = "0" * 64

    def __init__(self) -> None:
        self._entries: list[LogEntry] = []
        self._access_log: list[tuple[str, float, float]] = []  # auditor, ts_from, ts_to
        self._lock = threading.Lock()

    def ingest(self, source: str, timestamp: float, fields: dict) -> LogEntry:
        sens, masked = classify_and_mask(
            {k: str(v) for k, v in fields.items()}
        )
        with self._lock:
            prev = self._entries[-1].this_hash if self._entries else self.GENESIS
            idx = len(self._entries)
            payload = {"index": idx, "source": source, "timestamp": timestamp,
                       "sensitivity": sens, "fields": masked}
            e = LogEntry(index=idx, source=source, timestamp=timestamp,
                         sensitivity=sens, fields=masked,
                         prev_hash=prev, this_hash=_hash(prev, payload))
            self._entries.append(e)
            return e

    def entries(self) -> list[LogEntry]:
        with self._lock:
            return list(self._entries)

    def verify(self, entries: list[LogEntry] | None = None) -> bool:
        entries = entries if entries is not None else self.entries()
        prev = self.GENESIS
        for i, e in enumerate(entries):
            if e.index != i or e.prev_hash != prev:
                return False
            expected = _hash(prev, {
                "index": e.index, "source": e.source,
                "timestamp": e.timestamp, "sensitivity": e.sensitivity,
                "fields": e.fields,
            })
            if e.this_hash != expected:
                return False
            prev = e.this_hash
        return True

    def query(self, auditor: str, *, t_from: float, t_to: float,
              source: str | None = None) -> list[LogEntry]:
        with self._lock:
            self._access_log.append((auditor, t_from, t_to))
            hits = [e for e in self._entries
                    if t_from <= e.timestamp <= t_to
                    and (source is None or e.source == source)]
            return hits

    def access_log(self) -> list[tuple[str, float, float]]:
        with self._lock:
            return list(self._access_log)

    def retention_dry_run(
        self, *, now: float,
        general_ttl_s: float, pii_ttl_s: float,
    ) -> list[int]:
        """Return the list of entry indices eligible for deletion."""
        eligible: list[int] = []
        with self._lock:
            for e in self._entries:
                age = now - e.timestamp
                if e.sensitivity == "general" and age >= general_ttl_s:
                    eligible.append(e.index)
                elif e.sensitivity in ("pii", "pci", "health") and age >= pii_ttl_s:
                    eligible.append(e.index)
            return eligible
