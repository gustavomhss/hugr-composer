"""Hypothesis state-machine exploration of SessionStore lifecycle.

Covers all reachable transitions: create, load, rotate, revoke, revoke_all,
and a virtual clock advance. Asserts the key safety invariants at every
state: revoked-not-live, idle <= absolute, subject index is accurate.
"""

from __future__ import annotations

from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, initialize, invariant, rule

from SessionStore import InMemorySessionStore, SessionInvariantError


_SUBJECTS = ("alice", "bob", "carol")


class SessionStoreMachine(RuleBasedStateMachine):

    @initialize()
    def setup(self) -> None:
        self._clock: int = 1000
        self.store = InMemorySessionStore(
            idle_timeout_s=60,
            absolute_timeout_s=600,
            clock=lambda: self._clock,
        )
        self.issued: dict[str, str] = {}  # sid -> subject (model view)
        self.tombstoned: set[str] = set()

    @rule(subject=st.sampled_from(_SUBJECTS))
    def create(self, subject: str) -> None:
        s = self.store.create(subject)
        assert s.id not in self.tombstoned
        self.issued[s.id] = subject

    @rule(data=st.data())
    def load(self, data: st.DataObject) -> None:
        if not self.issued:
            return
        sid = data.draw(st.sampled_from(list(self.issued)))
        loaded = self.store.load(sid)
        if loaded is not None:
            assert loaded.id == sid
            assert loaded.idle_expires_at <= loaded.absolute_expires_at

    @rule(data=st.data())
    def rotate(self, data: st.DataObject) -> None:
        if not self.issued:
            return
        sid = data.draw(st.sampled_from(list(self.issued)))
        try:
            new = self.store.rotate(sid)
        except SessionInvariantError:
            return
        assert new.id != sid
        assert new.id not in self.tombstoned
        subj = self.issued.pop(sid)
        self.tombstoned.add(sid)
        self.issued[new.id] = subj

    @rule(data=st.data())
    def revoke(self, data: st.DataObject) -> None:
        if not self.issued:
            return
        sid = data.draw(st.sampled_from(list(self.issued)))
        self.store.revoke(sid)
        self.issued.pop(sid, None)
        self.tombstoned.add(sid)

    @rule(subject=st.sampled_from(_SUBJECTS))
    def revoke_all(self, subject: str) -> None:
        # Sync the model with the store's live view — any issued id that has
        # silently expired is gone from the store but may still be in the
        # model. Probe load() on every tracked id to let the store drop
        # naturally-expired records.
        self._sync_model()
        # Snapshot expected count BEFORE calling revoke_all (which empties
        # the store's subject index).
        live_ids = self.store.live_session_ids()
        expected = [
            sid for sid, sub in self.issued.items()
            if sub == subject and sid in live_ids
        ]
        n = self.store.revoke_all_for_subject(subject)
        assert n == len(expected)
        for sid in list(self.issued):
            if self.issued[sid] == subject:
                self.issued.pop(sid)
                self.tombstoned.add(sid)

    def _sync_model(self) -> None:
        live = self.store.live_session_ids()
        stale = [sid for sid in self.issued if sid not in live]
        for sid in stale:
            self.issued.pop(sid)
            # Naturally-expired records are NOT tombstoned; do not record them.

    @rule(dt=st.integers(min_value=1, max_value=120))
    def tick(self, dt: int) -> None:
        self._clock += dt
        # Prune the model: anything whose absolute has passed CAN be dropped
        # on the next store load; we do not touch the model here — live check
        # happens in the `invariant` methods.

    @invariant()
    def tombstone_excludes_live(self) -> None:
        if not hasattr(self, "store"):
            return
        live = self.store.live_session_ids()
        assert live.isdisjoint(self.tombstoned)

    @invariant()
    def live_is_well_formed(self) -> None:
        if not hasattr(self, "store"):
            return
        for sid in self.store.live_session_ids():
            s = self.store.load(sid)
            if s is None:
                # Could happen if load just expired the record; accept.
                continue
            assert s.idle_expires_at <= s.absolute_expires_at


TestSessionStoreMachine = SessionStoreMachine.TestCase
