"""BM25 retrieval over primitives_by_concern.yaml + primitive .md bodies.

Contract: B2.1 (CONTRACT.md §B).

- Pure retrieval, zero LLM calls, zero network.
- Index loaded once per process (module-level cache).
- Query latency target: p95 < 50 ms for N=97 primitives (enforced by tests).
- Ranking: BM25 (k1=1.5, b=0.75) over a weighted multi-field concatenation —
  name and concern are boosted so exact-name queries rank the primitive first.
"""
from __future__ import annotations

import math
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

import yaml

_REGISTRY_PATH = Path(__file__).resolve().parents[1] / "primitives_by_concern.yaml"
_VENOUS_ROOT = Path(__file__).resolve().parents[2] / "core" / "venous"

# BM25 knobs. Defaults from the original Okapi paper; safe for short docs.
_K1 = 1.5
_B = 0.75

# Field weights — expressed as integer repetitions of the field text before
# tokenization. A Rails-senior engineer querying "circuit breaker" expects
# `CircuitBreaker` to outrank a primitive that only mentions circuit breakers
# in its compose-with; boosting name + concern achieves that cleanly.
_WEIGHT_NAME = 5
_WEIGHT_CONCERN = 3
_WEIGHT_PURPOSE = 2
_WEIGHT_COMPOSE = 2
_WEIGHT_BODY = 1

_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9]+")

# Porter-light stem: ordered so "classes" (→ "class") and "class" (→ "class")
# converge. Rules are symmetric for query and index side; lengths-checked to
# avoid over-stemming short tokens ("bus" stays "bus").
def _stem(token: str) -> str:
    n = len(token)
    if n < 4:
        return token
    # Plural family — must check longest first to avoid double-stripping.
    if token.endswith("sses"):
        return token[:-2]                 # classes -> class, process kept elsewhere
    if token.endswith("ies") and n >= 5:
        return token[:-3] + "i"           # ponies -> poni, queries -> queri
    if token.endswith("ss"):
        return token                      # class, process, success, access
    if token.endswith("iers") and n >= 5:
        return token[:-4] + "i"           # verifiers -> verifi
    if token.endswith("ier") and n >= 5:
        return token[:-3] + "i"           # verifier -> verifi  (matches verify->verifi below)
    if token.endswith("ied") and n >= 5:
        return token[:-3] + "i"           # verified -> verifi
    if token.endswith("ers") and n >= 5:
        return token[:-3]                 # limiters -> limit
    if token.endswith("er") and n >= 5:
        return token[:-2]                 # limiter -> limit, logger -> log
    if token.endswith("ing") and n >= 6:
        return token[:-3]                 # hashing -> hash
    if token.endswith("ed") and n >= 5:
        return token[:-2]                 # hashed -> hash
    if token.endswith("es") and n >= 5:
        return token[:-2]                 # hashes -> hash
    if token.endswith("ly") and n >= 5:
        return token[:-2]                 # quickly -> quick
    if token.endswith("y") and n >= 4:
        return token[:-1] + "i"           # verify -> verifi (matches verifier->verifi above)
    if token.endswith("s") and n >= 4:
        return token[:-1]                 # hashes handled above; cats -> cat
    return token


def _camel_split(token: str) -> list[str]:
    """`CircuitBreaker` → `['circuit', 'breaker', 'circuitbreaker']`.

    Keeps the compound form so exact-name queries still score highly; adds
    the component words so `circuit breaker` (two tokens) also matches.
    """
    parts = re.findall(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|[0-9]+", token)
    parts = [p.lower() for p in parts if p]
    if len(parts) > 1:
        parts.append(token.lower())
    else:
        parts = [token.lower()]
    return parts


def _tokenize(text: str) -> list[str]:
    out: list[str] = []
    for match in _TOKEN_RE.findall(text):
        out.extend(_stem(t) for t in _camel_split(match))
    return out


@dataclass(frozen=True)
class PrimitiveHit:
    name: str
    namespace: str
    concern: str
    purpose: str
    score: float

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "namespace": self.namespace,
            "concern": self.concern,
            "purpose": self.purpose,
            "score": round(self.score, 4),
        }


class PrimitiveIndex:
    """BM25 index over the full registry. Build once, query many."""

    def __init__(self, registry_path: Path = _REGISTRY_PATH, venous_root: Path = _VENOUS_ROOT) -> None:
        self._registry_path = registry_path
        self._venous_root = venous_root
        self._entries: list[dict] = []
        self._tokens: list[list[str]] = []
        self._doc_len: list[int] = []
        self._term_freq: list[dict[str, int]] = []
        self._doc_freq: dict[str, int] = {}
        self._idf: dict[str, float] = {}
        self._avgdl: float = 0.0
        self._by_concern: dict[str, list[int]] = {}
        self._build()

    def _load_md_body(self, namespace: str, name: str) -> str:
        path = self._venous_root / namespace / name / f"{name}.md"
        if not path.is_file():
            return ""
        try:
            return path.read_text(encoding="utf-8")
        except OSError:
            return ""

    def _field_text(self, entry: dict) -> str:
        parts: list[str] = []
        parts.extend([entry["name"]] * _WEIGHT_NAME)
        parts.extend([entry["concern"]] * _WEIGHT_CONCERN)
        parts.extend([entry["namespace"]] * _WEIGHT_CONCERN)
        parts.extend([entry.get("purpose", "")] * _WEIGHT_PURPOSE)
        compose = " ".join(entry.get("compose_with") or [])
        parts.extend([compose] * _WEIGHT_COMPOSE)
        body = self._load_md_body(entry["namespace"], entry["name"])
        parts.extend([body] * _WEIGHT_BODY)
        return "\n".join(parts)

    def _build(self) -> None:
        with self._registry_path.open("r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}
        entries = raw.get("primitives") or []
        self._entries = [dict(e) for e in entries]

        total_len = 0
        for idx, entry in enumerate(self._entries):
            tokens = _tokenize(self._field_text(entry))
            self._tokens.append(tokens)
            self._doc_len.append(len(tokens))
            total_len += len(tokens)

            tf: dict[str, int] = {}
            for tok in tokens:
                tf[tok] = tf.get(tok, 0) + 1
            self._term_freq.append(tf)
            for tok in tf:
                self._doc_freq[tok] = self._doc_freq.get(tok, 0) + 1

            self._by_concern.setdefault(entry["concern"], []).append(idx)

        n = len(self._entries)
        self._avgdl = (total_len / n) if n else 0.0
        for term, df in self._doc_freq.items():
            self._idf[term] = math.log((n - df + 0.5) / (df + 0.5) + 1.0)

    # ------------------------------------------------------------------ query

    @property
    def concerns(self) -> list[str]:
        return sorted(self._by_concern.keys())

    @property
    def size(self) -> int:
        return len(self._entries)

    def _score(self, query_tokens: Sequence[str], doc_idx: int) -> float:
        tf = self._term_freq[doc_idx]
        dl = self._doc_len[doc_idx] or 1
        norm = _K1 * (1 - _B + _B * dl / (self._avgdl or 1))
        score = 0.0
        for tok in query_tokens:
            freq = tf.get(tok)
            if not freq:
                continue
            idf = self._idf.get(tok, 0.0)
            score += idf * (freq * (_K1 + 1)) / (freq + norm)
        return score

    def query(self, concern: str, query: str, limit: int = 10) -> list[PrimitiveHit]:
        if limit <= 0:
            return []
        concern_norm = (concern or "").strip().lower()
        query_norm = (query or "").strip()

        if concern_norm and concern_norm in self._by_concern:
            candidate_ids: Iterable[int] = self._by_concern[concern_norm]
        elif concern_norm:
            return []
        else:
            candidate_ids = range(len(self._entries))

        query_tokens = _tokenize(query_norm)

        if not query_tokens:
            hits = [
                PrimitiveHit(
                    name=self._entries[i]["name"],
                    namespace=self._entries[i]["namespace"],
                    concern=self._entries[i]["concern"],
                    purpose=self._entries[i].get("purpose", ""),
                    score=0.0,
                )
                for i in candidate_ids
            ]
            hits.sort(key=lambda h: h.name.lower())
            return hits[:limit]

        scored: list[tuple[float, int]] = []
        for i in candidate_ids:
            s = self._score(query_tokens, i)
            if s > 0:
                scored.append((s, i))
        scored.sort(key=lambda sx: (-sx[0], self._entries[sx[1]]["name"].lower()))

        return [
            PrimitiveHit(
                name=self._entries[i]["name"],
                namespace=self._entries[i]["namespace"],
                concern=self._entries[i]["concern"],
                purpose=self._entries[i].get("purpose", ""),
                score=s,
            )
            for s, i in scored[:limit]
        ]


_INDEX: PrimitiveIndex | None = None
_INDEX_LOCK = threading.Lock()


def get_index() -> PrimitiveIndex:
    global _INDEX
    if _INDEX is None:
        with _INDEX_LOCK:
            if _INDEX is None:
                _INDEX = PrimitiveIndex()
    return _INDEX


def find_primitive(concern: str = "", query: str = "", limit: int = 10) -> list[dict]:
    """Public retrieval API — MCP-facing.

    Args:
        concern: one of the registry's concern tags, or empty for all.
        query: natural-language fragment, e.g. "dedupe webhooks".
        limit: maximum hits (contract caps at 10).

    Returns:
        List of `{name, namespace, concern, purpose, score}` dicts,
        ranked by BM25 relevance descending.
    """
    limit = min(max(0, int(limit)), 10)
    if limit == 0:
        return []
    return [h.as_dict() for h in get_index().query(concern, query, limit=limit)]
