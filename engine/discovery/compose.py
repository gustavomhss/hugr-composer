"""Recipe retrieval over 'Compose with:' sections — CONTRACT §B2.2.

Parses every production primitive's ``Compose with:`` section, extracts
structured recipes of the form::

    - **<Name>** → `<PrimA>` + `<PrimB>`
      <rationale prose...>

and builds a BM25 index over combined ``name + rationale + primitive_names``.

Pure retrieval — zero LLM, zero network. Deterministic.
"""
from __future__ import annotations

import math
import re
import threading
from dataclasses import dataclass
from pathlib import Path

import yaml

from engine.discovery.find_primitive import _K1, _B, _tokenize

_REGISTRY_PATH = Path(__file__).resolve().parents[1] / "primitives_by_concern.yaml"
_VENOUS_ROOT = Path(__file__).resolve().parents[2] / "core" / "venous"

# Recipe line format used throughout the 97 production .md files.
_RECIPE_HEADER = re.compile(
    r"^\s*-\s+\*\*(?P<name>[^*]+?)\*\*\s*(?:→|->)\s*(?P<prims>.+?)\s*$"
)
_BACKTICK_NAME = re.compile(r"`([A-Za-z][A-Za-z0-9_]+)`")
_HEADING = re.compile(r"^## ", re.MULTILINE)


@dataclass(frozen=True)
class Recipe:
    source: str               # owning primitive name
    source_concern: str
    name: str                 # human-readable recipe title
    primitives: tuple[str, ...]
    rationale: str

    def doc_text(self) -> str:
        return " ".join([self.name, " ".join(self.primitives), self.rationale])


@dataclass(frozen=True)
class CompositionHit:
    primitives: tuple[str, ...]
    rationale: str
    score: float
    source: str
    name: str

    def as_dict(self) -> dict:
        return {
            "primitives": list(self.primitives),
            "rationale": self.rationale,
            "score": round(self.score, 4),
            "source": self.source,
            "name": self.name,
        }


def _extract_compose_section(md: str) -> str:
    """Return the text under the first '## Compose with' heading, or ''."""
    m = re.search(r"(?m)^##\s+Compose\s+with:?\s*$", md)
    if not m:
        return ""
    rest = md[m.end():]
    nxt = _HEADING.search(rest)
    return rest[: nxt.start()] if nxt else rest


def _parse_recipes(source: str, source_concern: str, md: str) -> list[Recipe]:
    sec = _extract_compose_section(md)
    if not sec:
        return []
    recipes: list[Recipe] = []
    # Recipes are bullets separated by blank lines; each bullet = header
    # line followed by indented rationale lines.
    blocks = re.split(r"\n\s*\n", sec.strip())
    for block in blocks:
        block = block.strip("\n")
        if not block:
            continue
        first_line, _, rest = block.partition("\n")
        head_match = _RECIPE_HEADER.match(first_line)
        if not head_match:
            continue
        name = head_match.group("name").strip()
        prims_raw = head_match.group("prims")
        # Primitive names come wrapped in backticks; the source primitive is
        # implicit — compositions ALWAYS include it.
        listed = tuple(_BACKTICK_NAME.findall(prims_raw))
        primitives: tuple[str, ...] = (source,) + tuple(p for p in listed if p != source)
        rationale = " ".join(line.strip() for line in rest.splitlines() if line.strip())
        recipes.append(Recipe(
            source=source,
            source_concern=source_concern,
            name=name,
            primitives=primitives,
            rationale=rationale,
        ))
    return recipes


class RecipeIndex:
    """BM25 over parsed recipes across all production primitives."""

    def __init__(
        self,
        registry_path: Path = _REGISTRY_PATH,
        venous_root: Path = _VENOUS_ROOT,
    ) -> None:
        self._registry_path = registry_path
        self._venous_root = venous_root
        self._recipes: list[Recipe] = []
        self._tokens: list[list[str]] = []
        self._doc_len: list[int] = []
        self._term_freq: list[dict[str, int]] = []
        self._doc_freq: dict[str, int] = {}
        self._idf: dict[str, float] = {}
        self._avgdl: float = 0.0
        self._build()

    def _build(self) -> None:
        raw = yaml.safe_load(self._registry_path.read_text(encoding="utf-8")) or {}
        entries = raw.get("primitives") or []
        for entry in entries:
            md_path = self._venous_root / entry["namespace"] / entry["name"] / f"{entry['name']}.md"
            if not md_path.is_file():
                continue
            try:
                md = md_path.read_text(encoding="utf-8")
            except OSError:
                continue
            self._recipes.extend(_parse_recipes(entry["name"], entry["concern"], md))

        total_len = 0
        for r in self._recipes:
            tokens = _tokenize(r.doc_text())
            self._tokens.append(tokens)
            self._doc_len.append(len(tokens))
            total_len += len(tokens)
            tf: dict[str, int] = {}
            for tok in tokens:
                tf[tok] = tf.get(tok, 0) + 1
            self._term_freq.append(tf)
            for tok in tf:
                self._doc_freq[tok] = self._doc_freq.get(tok, 0) + 1

        n = len(self._recipes)
        self._avgdl = (total_len / n) if n else 0.0
        for term, df in self._doc_freq.items():
            self._idf[term] = math.log((n - df + 0.5) / (df + 0.5) + 1.0)

    @property
    def size(self) -> int:
        return len(self._recipes)

    def _score(self, query_tokens: list[str], idx: int) -> float:
        tf = self._term_freq[idx]
        dl = self._doc_len[idx] or 1
        norm = _K1 * (1 - _B + _B * dl / (self._avgdl or 1))
        score = 0.0
        for tok in query_tokens:
            freq = tf.get(tok)
            if not freq:
                continue
            score += self._idf.get(tok, 0.0) * (freq * (_K1 + 1)) / (freq + norm)
        return score

    def query(self, intent: str, limit: int = 5) -> list[CompositionHit]:
        query_tokens = _tokenize(intent or "")
        if not query_tokens or limit <= 0:
            return []

        scored: list[tuple[float, int]] = []
        for i in range(len(self._recipes)):
            s = self._score(query_tokens, i)
            if s > 0:
                scored.append((s, i))
        scored.sort(key=lambda sx: (-sx[0], self._recipes[sx[1]].source.lower(), self._recipes[sx[1]].name.lower()))

        # Dedupe: same ordered primitive tuple should not appear twice even if
        # two source primitives describe it mutually.
        seen: set[tuple[str, ...]] = set()
        out: list[CompositionHit] = []
        for s, i in scored:
            r = self._recipes[i]
            key = tuple(sorted(r.primitives))
            if key in seen:
                continue
            seen.add(key)
            out.append(CompositionHit(
                primitives=r.primitives,
                rationale=r.rationale,
                score=s,
                source=r.source,
                name=r.name,
            ))
            if len(out) >= limit:
                break
        return out


_INDEX: RecipeIndex | None = None
_INDEX_LOCK = threading.Lock()


def get_recipe_index() -> RecipeIndex:
    global _INDEX
    if _INDEX is None:
        with _INDEX_LOCK:
            if _INDEX is None:
                _INDEX = RecipeIndex()
    return _INDEX


def suggest_composition(intent: str, limit: int = 5) -> list[dict]:
    """Rank compose-with recipes against a free-text intent.

    Args:
        intent: natural-language description of what the caller wants to build
            — e.g. ``"webhook receiver with dedupe and audit"``.
        limit: maximum compositions to return (1-5, capped at 5).

    Returns:
        List of ``{primitives, rationale, score, source, name}`` dicts
        ranked by BM25 descending. Zero LLM calls, zero network.
    """
    limit = min(max(0, int(limit)), 5)
    if limit == 0:
        return []
    return [h.as_dict() for h in get_recipe_index().query(intent, limit=limit)]
