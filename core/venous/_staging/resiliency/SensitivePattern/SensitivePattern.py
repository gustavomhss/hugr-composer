from __future__ import annotations
from dataclasses import dataclass
import re


@dataclass(frozen=True)
class SensitivePattern:
    """A named regex pattern with its sensitivity category.

    Attributes:
        name: Human-readable pattern name.
        regex: Compiled regular expression.
        level: Sensitivity level: 'pci', 'pii', 'phi', 'custom'.
    """
    name: str
    regex: re.Pattern[str]
    level: str
