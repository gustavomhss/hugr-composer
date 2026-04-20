"""Hypothesis state-machine for StreamSubject."""

from __future__ import annotations

from hypothesis import settings
from hypothesis.stateful import RuleBasedStateMachine, invariant, rule
from hypothesis.strategies import sampled_from

from StreamSubject import StreamSubject, SubjectRegistry


PATTERNS = ("a.>", "a.*.v1", "a.b.c", "b.>", "c.*")
SUBJECTS = ("a.b.v1", "a.c.v1", "a.b.c", "b.x", "c.z", "d.e")
SUBSCRIBERS = ("c1", "c2", "c3")


class StreamSubjectMachine(RuleBasedStateMachine):
    def __init__(self) -> None:
        super().__init__()
        self.reg = SubjectRegistry()
        self.published_count = 0

    @rule(pattern=sampled_from(PATTERNS), sid=sampled_from(SUBSCRIBERS))
    def subscribe(self, pattern: str, sid: str) -> None:
        self.reg.subscribe(pattern, sid)

    @rule(pattern=sampled_from(PATTERNS), sid=sampled_from(SUBSCRIBERS))
    def unsubscribe(self, pattern: str, sid: str) -> None:
        self.reg.unsubscribe(pattern, sid)

    @rule(name=sampled_from(SUBJECTS))
    def publish(self, name: str) -> None:
        count = self.reg.publish(StreamSubject(name))
        self.published_count += count

    @invariant()
    def delivered_implies_match(self) -> None:
        for pattern, subject_name, _seq in self.reg.deliveries():
            assert StreamSubject(subject_name).matches(pattern)


TestStreamSubjectMachine = StreamSubjectMachine.TestCase
TestStreamSubjectMachine.settings = settings(max_examples=40, stateful_step_count=25)
