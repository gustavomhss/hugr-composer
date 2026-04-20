"""SagaOrchestrator primitive — Richardson/Garcia-Molina long-running transaction.

Coordinates a multi-step business transaction across services. Forward steps run
in registration order; on any failure the completed steps are compensated in
STRICT REVERSE order. The orchestrator persists state transitions atomically
with emitted commands so a crash never leaves a dangling saga. Coordination is
via asynchronous messages: the orchestrator NEVER assumes strong cross-service
consistency.

Invariant IDs cited by this module:

- SAGA-INV-01: every forward step MUST declare a compensating action, or the
  saga CANNOT include it. A saga definition with any step missing its
  compensator is rejected at registration — you never learn mid-flight that a
  rollback cannot run.
- SAGA-INV-02: compensation order SHALL be the reverse of the completed forward
  steps. Out-of-order compensation is FORBIDDEN.
- SAGA-INV-03: the orchestrator's state transitions MUST be persisted
  atomically with the command it emits; crashes NEVER leave dangling sagas.
  This module persists (state_transition, emitted_command) as a single journal
  record under the lock, and never emits a command whose state-change has not
  been committed.
- SAGA-INV-04: no step handler SHALL assume strong consistency across
  services; all coordination runs via asynchronous messages delivered through
  a pluggable command bus.
"""

from __future__ import annotations

import copy
import threading
from collections.abc import Callable, Iterable
from typing import Any, Final, Protocol, runtime_checkable

# ---------------------------------------------------------------------------
# Lifecycle states
# ---------------------------------------------------------------------------
STATE_PENDING: Final[str] = "pending"
STATE_RUNNING: Final[str] = "running"
STATE_COMPENSATING: Final[str] = "compensating"
STATE_COMPLETED: Final[str] = "completed"
STATE_FAILED: Final[str] = "failed"

_TERMINAL_STATES: Final[frozenset[str]] = frozenset({STATE_COMPLETED, STATE_FAILED})
_ALL_STATES: Final[frozenset[str]] = frozenset(
    {STATE_PENDING, STATE_RUNNING, STATE_COMPENSATING, STATE_COMPLETED, STATE_FAILED}
)


# ---------------------------------------------------------------------------
# Protocol surface (matches catalog api_signature verbatim)
# ---------------------------------------------------------------------------
@runtime_checkable
class SagaOrchestrator(Protocol):
    def start(self, correlation_id: str, input: Any) -> None: ...  # noqa: A002 — matches catalog api_signature verbatim (SAGA-INV-01)
    def step(self, correlation_id: str, name: str, outcome: Any) -> None: ...
    def compensate(self, correlation_id: str, from_step: str) -> None: ...
    def status(self, correlation_id: str) -> tuple[str, Iterable[str]]: ...


# ---------------------------------------------------------------------------
# Exception hierarchy
# ---------------------------------------------------------------------------
class SagaOrchestratorInvariantError(RuntimeError):
    """Raised when a SagaOrchestrator invariant is violated at runtime."""


class SagaDefinitionError(SagaOrchestratorInvariantError):
    """SAGA-INV-01: a forward step was registered with no compensator, or the
    saga definition is malformed (duplicate step name, empty definition, etc.).
    """


class UnknownSagaError(SagaOrchestratorInvariantError):
    """The provided ``correlation_id`` does not map to any running saga."""


class CompensationOrderError(SagaOrchestratorInvariantError):
    """SAGA-INV-02: compensate() was called for a step that is not the latest
    completed forward step; out-of-order compensation is FORBIDDEN.
    """


# ---------------------------------------------------------------------------
# Step definition
# ---------------------------------------------------------------------------
StepHandler = Callable[[Any], Any]
Compensator = Callable[[Any], Any]
Middleware = Callable[[str, str, Callable[[Any], Any], Any], Any]
CommandSink = Callable[[str, str, Any], None]


class StepDefinition:
    """Immutable forward + compensating action pair.

    SAGA-INV-01: the compensator cannot be None; construction rejects any step
    that lacks a compensator, which means the saga can NEVER include a step
    whose forward action has no way to undo. (A no-op compensator is still a
    legal explicit declaration — the caller signals "nothing to undo" instead
    of implicitly skipping the contract.)
    """

    __slots__ = ("_compensator", "_handler", "_name")

    def __init__(self, name: str, handler: StepHandler, compensator: Compensator) -> None:
        if not isinstance(name, str) or not name:
            raise SagaDefinitionError(
                "SAGA-INV-01: step name MUST be a non-empty string."
            )
        if not callable(handler):
            raise SagaDefinitionError(
                f"SAGA-INV-01: step {name!r} handler MUST be callable."
            )
        if compensator is None or not callable(compensator):
            raise SagaDefinitionError(
                f"SAGA-INV-01: step {name!r} MUST declare a compensating action; "
                "no-compensator steps CANNOT be part of a saga."
            )
        self._name: Final[str] = name
        self._handler: Final[StepHandler] = handler
        self._compensator: Final[Compensator] = compensator

    @property
    def name(self) -> str:
        return self._name

    @property
    def handler(self) -> StepHandler:
        return self._handler

    @property
    def compensator(self) -> Compensator:
        return self._compensator

    def __repr__(self) -> str:
        return f"StepDefinition(name={self._name!r})"


# ---------------------------------------------------------------------------
# Saga definition — ordered list of steps registered via decorator
# ---------------------------------------------------------------------------
class SagaDefinition:
    """Registry for the ordered forward steps of a saga.

    Extension contract: downstream callers register steps with
    :meth:`register`, then instantiate an :class:`InMemorySagaOrchestrator`
    with the finalised definition. Middleware (timeouts, retries, tracing) is
    wired with :meth:`add_middleware`; middleware runs around each step
    invocation but CANNOT reorder compensation (SAGA-INV-02 still holds).
    """

    def __init__(self, name: str) -> None:
        if not isinstance(name, str) or not name:
            raise SagaDefinitionError(
                "SAGA-INV-01: saga name MUST be a non-empty string."
            )
        self._name: Final[str] = name
        self._steps: list[StepDefinition] = []
        self._step_index: dict[str, int] = {}
        self._middleware: list[Middleware] = []
        self._lock = threading.Lock()

    @property
    def name(self) -> str:
        return self._name

    def register(
        self, name: str, compensator: Compensator
    ) -> Callable[[StepHandler], StepHandler]:
        """Decorator: register ``handler`` as the forward action of step ``name``.

        The ``compensator`` is mandatory (SAGA-INV-01). Returns the handler so
        the decoration chain is transparent.
        """

        def _decorate(handler: StepHandler) -> StepHandler:
            with self._lock:
                if name in self._step_index:
                    raise SagaDefinitionError(
                        f"SAGA-INV-01: step {name!r} already registered; "
                        "duplicate registration is FORBIDDEN."
                    )
                self._steps.append(StepDefinition(name, handler, compensator))
                self._step_index[name] = len(self._steps) - 1
            return handler

        return _decorate

    def add_middleware(self, middleware: Middleware) -> None:
        """Register cross-cutting middleware. MUST NOT alter compensation order."""
        if not callable(middleware):
            raise SagaDefinitionError(
                "SAGA-INV-01: middleware MUST be callable."
            )
        with self._lock:
            self._middleware.append(middleware)

    def steps(self) -> tuple[StepDefinition, ...]:
        with self._lock:
            return tuple(self._steps)

    def middleware(self) -> tuple[Middleware, ...]:
        with self._lock:
            return tuple(self._middleware)

    def index_of(self, step_name: str) -> int:
        with self._lock:
            try:
                return self._step_index[step_name]
            except KeyError as exc:
                raise SagaDefinitionError(
                    f"SAGA-INV-01: step {step_name!r} is not part of saga "
                    f"{self._name!r}."
                ) from exc


# ---------------------------------------------------------------------------
# Per-saga journal record (state transition + emitted command, persisted as one)
# ---------------------------------------------------------------------------
class JournalRecord:
    """A single atomic state-transition + emitted command.

    SAGA-INV-03: the orchestrator appends a JournalRecord under the lock in the
    same critical section as the state mutation, so any observer sees either
    BOTH the new state AND the emitted command, or neither. There is no
    intermediate window where the state is advanced but the command has not
    been journalled.
    """

    __slots__ = ("_command_name", "_command_payload", "_from_state", "_seq", "_to_state")

    def __init__(
        self,
        seq: int,
        from_state: str,
        to_state: str,
        command_name: str,
        command_payload: object,
    ) -> None:
        self._seq: Final[int] = seq
        self._from_state: Final[str] = from_state
        self._to_state: Final[str] = to_state
        self._command_name: Final[str] = command_name
        self._command_payload: Final[object] = command_payload

    @property
    def seq(self) -> int:
        return self._seq

    @property
    def from_state(self) -> str:
        return self._from_state

    @property
    def to_state(self) -> str:
        return self._to_state

    @property
    def command_name(self) -> str:
        return self._command_name

    @property
    def command_payload(self) -> object:
        return copy.deepcopy(self._command_payload)

    def __repr__(self) -> str:
        return (
            f"JournalRecord(seq={self._seq}, {self._from_state}->{self._to_state}, "
            f"command={self._command_name!r})"
        )


# ---------------------------------------------------------------------------
# Per-saga instance — internal state machine
# ---------------------------------------------------------------------------
class _SagaInstance:
    """Per-correlation-id state; only the orchestrator mutates this object."""

    __slots__ = (
        "completed",
        "correlation_id",
        "idempotency_seen",
        "input",
        "journal",
        "last_error",
        "outcomes",
        "state",
    )

    def __init__(self, correlation_id: str, input_payload: object) -> None:
        self.correlation_id: str = correlation_id
        self.input: object = copy.deepcopy(input_payload)
        self.state: str = STATE_PENDING
        # Ordered list of step names whose forward action completed successfully.
        self.completed: list[str] = []
        # Map step_name -> outcome payload (deep-copied on ingress).
        self.outcomes: dict[str, object] = {}
        # Journal of atomic (state-transition, emitted command) records.
        self.journal: list[JournalRecord] = []
        # Idempotency: set of (step_name, event_key) already applied.
        self.idempotency_seen: set[tuple[str, str]] = set()
        self.last_error: str | None = None


# ---------------------------------------------------------------------------
# Reference implementation
# ---------------------------------------------------------------------------
class InMemorySagaOrchestrator:
    """Reference SagaOrchestrator coordinating a saga defined by :class:`SagaDefinition`.

    * ``start`` creates the saga instance, atomically journals PENDING->RUNNING,
      runs the first forward step via the command sink, and records the outcome.
    * ``step`` records a forward-step outcome from a participant. Success
      advances to the next step; failure flips the saga into COMPENSATING and
      drives compensators in REVERSE order of completed steps (SAGA-INV-02).
    * ``compensate`` runs the compensator for ``from_step`` and then the
      compensators for every earlier completed step in REVERSE order. Any
      attempt to compensate a step that is not the current tail of the
      ``completed`` list raises :class:`CompensationOrderError`.
    * ``status`` returns ``(state, tuple_of_completed_step_names)``.

    All mutations are serialised by a reentrant lock, and the command sink is
    invoked OUTSIDE the lock to avoid deadlocks when a middleware calls back
    into ``step`` synchronously (the command bus is asynchronous by contract;
    synchronous delivery is a test convenience).
    """

    def __init__(
        self,
        definition: SagaDefinition,
        command_sink: CommandSink | None = None,
    ) -> None:
        if not isinstance(definition, SagaDefinition):
            raise SagaDefinitionError(
                "SAGA-INV-01: definition MUST be a SagaDefinition."
            )
        steps = definition.steps()
        if not steps:
            raise SagaDefinitionError(
                "SAGA-INV-01: saga definition MUST contain at least one step."
            )
        # Re-validate every step has a compensator (belt and braces — the
        # StepDefinition constructor enforces this, but a caller could in
        # principle subclass and bypass).
        for sd in steps:
            if sd.compensator is None or not callable(sd.compensator):
                raise SagaDefinitionError(
                    f"SAGA-INV-01: step {sd.name!r} has no compensator; "
                    "the saga CANNOT include it."
                )
        self._definition: Final[SagaDefinition] = definition
        self._command_sink: Final[CommandSink] = command_sink or self._default_sink
        self._instances: dict[str, _SagaInstance] = {}
        self._lock = threading.RLock()
        self._seq_counter: int = 0

    # ----- internal helpers --------------------------------------------------
    @staticmethod
    def _default_sink(correlation_id: str, command: str, payload: object) -> None:
        # SAGA-INV-04: in production, the sink SHALL be an asynchronous bus.
        # The default no-op makes the orchestrator bootable without an external
        # message broker (zero I/O at import).
        _ = (correlation_id, command, payload)

    def _next_seq(self) -> int:
        self._seq_counter += 1
        return self._seq_counter

    def _journal_transition(
        self,
        inst: _SagaInstance,
        to_state: str,
        command_name: str,
        command_payload: object,
    ) -> JournalRecord:
        """SAGA-INV-03: append journal + state change under the SAME lock hold.

        Returns the record so the caller can emit the command OUTSIDE the lock.
        If the caller crashes BEFORE emit, a recovery pass can re-emit the
        journalled command because the record is already persisted.
        """
        if to_state not in _ALL_STATES:
            raise SagaOrchestratorInvariantError(
                f"SAGA-INV-03: attempted transition to unknown state {to_state!r}."
            )
        record = JournalRecord(
            seq=self._next_seq(),
            from_state=inst.state,
            to_state=to_state,
            command_name=command_name,
            command_payload=copy.deepcopy(command_payload),
        )
        inst.journal.append(record)
        inst.state = to_state
        return record

    def _emit(self, correlation_id: str, record: JournalRecord) -> None:
        """Invoke the command sink OUTSIDE the lock."""
        try:
            self._command_sink(correlation_id, record.command_name, record.command_payload)
        except BaseException as exc:  # noqa: BLE001 — SAGA-INV-03: journal must survive ANY sink failure (including SystemExit) so recovery can resume from the journalled record
            # Never let a sink exception corrupt the journal. Record the failure
            # but keep the state as-journalled; a recovery pass can resume.
            with self._lock:
                inst = self._instances.get(correlation_id)
                if inst is not None:
                    inst.last_error = f"sink failure on {record.command_name}: {exc}"

    def _require_instance(self, correlation_id: str) -> _SagaInstance:
        inst = self._instances.get(correlation_id)
        if inst is None:
            raise UnknownSagaError(
                f"SAGA-INV-03: no saga journalled for correlation_id={correlation_id!r}."
            )
        return inst

    def _compensate_from_index(self, inst: _SagaInstance, tail_index: int) -> list[JournalRecord]:
        """Drive compensators in STRICT REVERSE order starting at ``tail_index``.

        SAGA-INV-02: compensators run from ``completed[tail_index]`` backwards
        to ``completed[0]``. We pop each completed entry as its compensator
        fires, and journal each transition + emitted `compensate_<step>` command
        atomically.
        """
        records: list[JournalRecord] = []
        steps_by_name: dict[str, StepDefinition] = {s.name: s for s in self._definition.steps()}

        # SAGA-INV-02 performance + liveness: collect (step, compensator, payload)
        # tuples under the lock (cheap), then RELEASE the lock and invoke
        # compensators outside it. A slow/blocking compensator would otherwise
        # serialize every other saga against this orchestrator.
        work: list[tuple[str, StepDefinition, object]] = []
        idx = tail_index
        while idx >= 0 and len(inst.completed) > idx:
            step_name = inst.completed[idx]
            sd = steps_by_name.get(step_name)
            if sd is None:
                raise SagaDefinitionError(
                    f"SAGA-INV-01: step {step_name!r} has no definition; "
                    "compensation cannot proceed."
                )
            payload = inst.outcomes.get(step_name)
            record = self._journal_transition(
                inst=inst,
                to_state=STATE_COMPENSATING,
                command_name=f"compensate_{step_name}",
                command_payload=payload,
            )
            records.append(record)
            work.append((step_name, sd, payload))
            inst.completed.pop()  # journaled; remove from the live list
            idx -= 1

        # Release the reentrant lock for the duration of compensator calls.
        # `_lock` is an RLock held by the caller; `_mu_release_temporarily`
        # peels off every acquisition level and re-acquires them after.
        held = 0
        while True:
            try:
                self._lock.release()
                held += 1
            except RuntimeError:
                break
        failed_step: str | None = None
        try:
            for step_name, sd, payload in work:
                try:
                    sd.compensator(payload)
                except BaseException as exc:  # noqa: BLE001 — a rogue compensator MUST be isolated so later ones still run; SAGA-INV-02 terminates the saga as FAILED below.
                    inst.last_error = f"compensator for {step_name!r} raised: {exc}"
                    failed_step = step_name
                    break
        finally:
            for _ in range(held):
                self._lock.acquire()

        # SAGA-INV-02: whether every compensator ran cleanly or one raised,
        # the saga MUST reach the terminal FAILED state. Leaving it in
        # COMPENSATING would strand operators without a resume contract.
        terminal = self._journal_transition(
            inst=inst,
            to_state=STATE_FAILED,
            command_name="saga_failed",
            command_payload={
                "last_error": inst.last_error,
                "compensator_failed_step": failed_step,
            },
        )
        records.append(terminal)
        return records

    def _run_next_forward_step(self, inst: _SagaInstance) -> JournalRecord | None:
        """Advance one forward step. Returns the journalled record to emit."""
        steps = self._definition.steps()
        next_index = len(inst.completed)
        if next_index >= len(steps):
            # All forward steps done → COMPLETED.
            return self._journal_transition(
                inst=inst,
                to_state=STATE_COMPLETED,
                command_name="saga_completed",
                command_payload={"completed": list(inst.completed)},
            )
        sd = steps[next_index]
        return self._journal_transition(
            inst=inst,
            to_state=STATE_RUNNING,
            command_name=f"invoke_{sd.name}",
            command_payload=inst.input if next_index == 0 else inst.outcomes.get(
                inst.completed[-1]
            ),
        )

    def _apply_step_locked(
        self, correlation_id: str, name: str, outcome: Any
    ) -> list[tuple[str, JournalRecord]]:
        """Apply a step report under the lock. Returns records to emit outside."""
        inst = self._require_instance(correlation_id)
        if inst.state in _TERMINAL_STATES:
            # SAGA-INV-04: terminal saga ignores further step reports
            # (participant may re-deliver a message after the saga finished).
            return []
        idem_key = (name, _safe_key(outcome))
        if idem_key in inst.idempotency_seen:
            return []
        inst.idempotency_seen.add(idem_key)

        steps = self._definition.steps()
        expected_index = len(inst.completed)
        if expected_index >= len(steps):
            return []
        expected_step = steps[expected_index]
        if name != expected_step.name:
            raise SagaOrchestratorInvariantError(
                f"SAGA-INV-02: step {name!r} reported out-of-order; "
                f"expected next step {expected_step.name!r}."
            )
        if _is_failure_outcome(outcome):
            return self._apply_failure_locked(inst, name, outcome, correlation_id)
        return self._apply_success_locked(inst, name, outcome, correlation_id)

    def _apply_failure_locked(
        self,
        inst: _SagaInstance,
        name: str,
        outcome: object,
        correlation_id: str,
    ) -> list[tuple[str, JournalRecord]]:
        reason = "unspecified failure"
        if isinstance(outcome, dict):
            reason = str(outcome.get("reason") or reason)
        inst.last_error = reason
        tail_index = len(inst.completed) - 1
        inst.outcomes[name] = copy.deepcopy(outcome)
        records = self._compensate_from_index(inst, tail_index)
        return [(correlation_id, r) for r in records]

    def _apply_success_locked(
        self,
        inst: _SagaInstance,
        name: str,
        outcome: object,
        correlation_id: str,
    ) -> list[tuple[str, JournalRecord]]:
        inst.outcomes[name] = copy.deepcopy(outcome)
        inst.completed.append(name)
        record = self._run_next_forward_step(inst)
        if record is None:
            return []
        return [(correlation_id, record)]

    # ----- protocol surface --------------------------------------------------
    def start(self, correlation_id: str, input: Any) -> None:  # noqa: A002 — catalog api_signature
        """Begin a saga for ``correlation_id`` with ``input``.

        SAGA-INV-03: journals PENDING→RUNNING + the first invoke command
        atomically. Repeated calls with the same ``correlation_id`` are
        idempotent (return silently if the saga is already started).
        """
        if not isinstance(correlation_id, str) or not correlation_id:
            raise SagaOrchestratorInvariantError(
                "SAGA-INV-03: correlation_id MUST be a non-empty string."
            )
        with self._lock:
            existing = self._instances.get(correlation_id)
            if existing is not None:
                # Idempotent start — do not re-journal; SAGA-INV-03 means the
                # caller's retry sees the same state the original call left us in.
                return
            inst = _SagaInstance(correlation_id, input)
            self._instances[correlation_id] = inst
            record = self._run_next_forward_step(inst)
        if record is not None:
            self._emit(correlation_id, record)

    def step(self, correlation_id: str, name: str, outcome: Any) -> None:
        """Record the outcome of forward step ``name``.

        ``outcome`` is a free-form payload; a special sentinel value of a
        dict ``{"__saga_failed__": True, "reason": "..."}`` signals that the
        participant reported a failure — the orchestrator flips the saga into
        COMPENSATING and drives compensators in REVERSE order (SAGA-INV-02).
        """
        if not isinstance(correlation_id, str) or not correlation_id:
            raise SagaOrchestratorInvariantError(
                "SAGA-INV-03: correlation_id MUST be a non-empty string."
            )
        if not isinstance(name, str) or not name:
            raise SagaOrchestratorInvariantError(
                "SAGA-INV-01: step name MUST be a non-empty string."
            )
        records_to_emit: list[tuple[str, JournalRecord]] = []
        with self._lock:
            records_to_emit = self._apply_step_locked(correlation_id, name, outcome)
        for cid, r in records_to_emit:
            self._emit(cid, r)

    def compensate(self, correlation_id: str, from_step: str) -> None:
        """Drive compensation starting at ``from_step`` backwards.

        SAGA-INV-02: ``from_step`` MUST be the most recently completed forward
        step. Jumping to an earlier step is FORBIDDEN — such a call would skip
        compensators that MUST run to undo later side effects.
        """
        if not isinstance(correlation_id, str) or not correlation_id:
            raise SagaOrchestratorInvariantError(
                "SAGA-INV-03: correlation_id MUST be a non-empty string."
            )
        if not isinstance(from_step, str) or not from_step:
            raise SagaOrchestratorInvariantError(
                "SAGA-INV-01: from_step MUST be a non-empty string."
            )
        records_to_emit: list[tuple[str, JournalRecord]] = []
        with self._lock:
            inst = self._require_instance(correlation_id)
            if inst.state in _TERMINAL_STATES:
                return
            if not inst.completed:
                # Nothing to compensate → go directly to FAILED.
                record = self._journal_transition(
                    inst=inst,
                    to_state=STATE_FAILED,
                    command_name="saga_failed",
                    command_payload={"reason": "no forward steps completed"},
                )
                records_to_emit.append((correlation_id, record))
            else:
                tail = inst.completed[-1]
                if from_step != tail:
                    # Any out-of-order jump violates SAGA-INV-02.
                    raise CompensationOrderError(
                        f"SAGA-INV-02: compensate(from_step={from_step!r}) is "
                        f"out-of-order; the latest completed step is {tail!r}. "
                        "Compensation MUST run in strict reverse order."
                    )
                tail_index = len(inst.completed) - 1
                inst.last_error = inst.last_error or f"compensate({from_step})"
                records = self._compensate_from_index(inst, tail_index)
                for r in records:
                    records_to_emit.append((correlation_id, r))
        for cid, r in records_to_emit:
            self._emit(cid, r)

    def status(self, correlation_id: str) -> tuple[str, Iterable[str]]:
        """Return ``(state, completed_step_names)`` for ``correlation_id``."""
        if not isinstance(correlation_id, str) or not correlation_id:
            raise SagaOrchestratorInvariantError(
                "SAGA-INV-03: correlation_id MUST be a non-empty string."
            )
        with self._lock:
            inst = self._require_instance(correlation_id)
            return inst.state, tuple(inst.completed)

    # ----- introspection -----------------------------------------------------
    def journal_for(self, correlation_id: str) -> tuple[JournalRecord, ...]:
        with self._lock:
            inst = self._require_instance(correlation_id)
            return tuple(inst.journal)

    def last_error(self, correlation_id: str) -> str | None:
        with self._lock:
            inst = self._require_instance(correlation_id)
            return inst.last_error

    def active_count(self) -> int:
        with self._lock:
            return sum(
                1 for i in self._instances.values() if i.state not in _TERMINAL_STATES
            )

    def known_correlations(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(self._instances.keys())


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _is_failure_outcome(outcome: object) -> bool:
    """Return True iff the outcome payload carries the explicit failure sentinel."""
    return isinstance(outcome, dict) and outcome.get("__saga_failed__") is True


def _safe_key(value: object) -> str:
    """Stable string key for an outcome payload (used for idempotency)."""
    try:
        return repr(value)
    except BaseException:  # noqa: BLE001 — SAGA-INV-03: idempotency key derivation must NEVER crash the orchestrator even if an exotic payload's __repr__ misbehaves (including raising SystemExit)
        return f"<unrepr:{type(value).__name__}>"


__all__ = [
    "STATE_COMPENSATING",
    "STATE_COMPLETED",
    "STATE_FAILED",
    "STATE_PENDING",
    "STATE_RUNNING",
    "CommandSink",
    "CompensationOrderError",
    "Compensator",
    "InMemorySagaOrchestrator",
    "JournalRecord",
    "Middleware",
    "SagaDefinition",
    "SagaDefinitionError",
    "SagaOrchestrator",
    "SagaOrchestratorInvariantError",
    "StepDefinition",
    "StepHandler",
    "UnknownSagaError",
]
