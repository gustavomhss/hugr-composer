"""Shared English pluralization helper used by multiple generators.

This is intentionally small — a full ``inflect`` library would be overkill.
It handles the common English plural rules plus a small irregular dictionary
so generated code uses correct plurals (``Categories``, not ``Categorys``).
"""

from __future__ import annotations

import re

_IRREGULAR: dict[str, str] = {
    "person": "people",
    "child": "children",
    "mouse": "mice",
    "goose": "geese",
    "ox": "oxen",
    "category": "categories",
    "city": "cities",
    "company": "companies",
    "country": "countries",
    "story": "stories",
    "party": "parties",
    "factory": "factories",
    "family": "families",
}


def pluralize(word: str) -> str:
    """Return a naive English plural for *word*.

    Preserves the capitalization of the first letter when an irregular
    plural is returned (``Category`` -> ``Categories``).
    """
    lower = word.lower()
    if lower in _IRREGULAR:
        plural = _IRREGULAR[lower]
        if word[:1].isupper():
            return plural[:1].upper() + plural[1:]
        return plural
    if re.search(r"(s|x|z|ch|sh)$", lower):
        return word + "es"
    if re.search(r"[^aeiou]y$", lower):
        return word[:-1] + "ies"
    return word + "s"
