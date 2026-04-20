"""Hypothesis state-machine exploration for PiiClassification."""

from __future__ import annotations

from dataclasses import make_dataclass

from hypothesis import settings
from hypothesis.stateful import RuleBasedStateMachine, rule

from PiiClassification import InMemoryPiiClassification, PiiClass


_CLASSES = [PiiClass.PUBLIC, PiiClass.INTERNAL, PiiClass.PII, PiiClass.PHI, PiiClass.PCI]


class PiiStateMachine(RuleBasedStateMachine):
    def __init__(self) -> None:
        super().__init__()
        self.classifier = InMemoryPiiClassification()
        self.shadow: dict[tuple[str, str], PiiClass] = {}
        self.model_cls = make_dataclass("M", [("x", str), ("y", str)])

    def _try_register(self, field: str, new_cls: PiiClass) -> None:
        """Invariant-respecting register: only commits on upward moves."""
        from PiiClassification import PiiClassificationError
        try:
            self.classifier.register(self.model_cls, field, new_cls)
        except PiiClassificationError:
            # PIC_INV_05: downward without approver is correctly refused.
            return
        self.shadow[("M", field)] = new_cls

    @rule()
    def register_x_public(self) -> None:
        self._try_register("x", PiiClass.PUBLIC)

    @rule()
    def register_x_pii(self) -> None:
        self._try_register("x", PiiClass.PII)

    @rule()
    def register_y_phi(self) -> None:
        self._try_register("y", PiiClass.PHI)

    @rule()
    def leak(self) -> None:
        self.classifier.audit_leak(object(), sink="sink")

    def teardown(self) -> None:
        # PIC_INV_01: every registered field classifies back to its shadow value.
        for (_, field), cls in self.shadow.items():
            assert self.classifier.classify(self.model_cls, field) is cls


TestPii = PiiStateMachine.TestCase
TestPii.settings = settings(max_examples=30, deadline=None)
