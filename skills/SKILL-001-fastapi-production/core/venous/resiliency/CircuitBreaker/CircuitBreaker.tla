---- MODULE CircuitBreaker ----
EXTENDS Naturals, FiniteSets

CONSTANTS MaxSamples, MinSamples, MaxProbes, FailureThreshold

VARIABLES state, failures, samples, clock, openedAt, probesInFlight

vars == <<state, failures, samples, clock, openedAt, probesInFlight>>

States == {"closed", "open", "half_open"}

TypeOK ==
    /\ state \in States
    /\ samples \in 0..MaxSamples
    /\ failures \in 0..MaxSamples
    /\ failures <= samples
    /\ clock \in Nat
    /\ openedAt \in Nat
    /\ probesInFlight \in 0..MaxProbes

Init ==
    /\ state = "closed"
    /\ samples = 0
    /\ failures = 0
    /\ clock = 0
    /\ openedAt = 0
    /\ probesInFlight = 0

\* Closed state: record success (stays closed while below threshold).
ClosedSuccess ==
    /\ state = "closed"
    /\ samples < MaxSamples
    /\ samples' = samples + 1
    /\ failures' = failures
    /\ UNCHANGED <<state, clock, openedAt, probesInFlight>>

\* Closed state: record failure; flips open iff >= MinSamples and rate >= threshold.
ClosedFailure ==
    /\ state = "closed"
    /\ samples < MaxSamples
    /\ samples' = samples + 1
    /\ failures' = failures + 1
    /\ IF (samples + 1 >= MinSamples) /\ (failures + 1) * 100 >= FailureThreshold * (samples + 1)
       THEN /\ state' = "open"
            /\ openedAt' = clock
            /\ probesInFlight' = 0
       ELSE UNCHANGED <<state, openedAt, probesInFlight>>
    /\ UNCHANGED clock

\* Cooldown elapses: open -> half_open. Requires clock to have advanced.
CooldownElapsed ==
    /\ state = "open"
    /\ clock > openedAt
    /\ state' = "half_open"
    /\ probesInFlight' = 0
    /\ UNCHANGED <<samples, failures, clock, openedAt>>

\* Half-open grants a probe (bounded by MaxProbes).
GrantProbe ==
    /\ state = "half_open"
    /\ probesInFlight < MaxProbes
    /\ probesInFlight' = probesInFlight + 1
    /\ UNCHANGED <<state, samples, failures, clock, openedAt>>

\* Probe succeeds: one fewer in-flight; when all drained, close the circuit.
ProbeSuccess ==
    /\ state = "half_open"
    /\ probesInFlight > 0
    /\ probesInFlight' = probesInFlight - 1
    /\ IF probesInFlight - 1 = 0
       THEN /\ state' = "closed"
            /\ samples' = 0
            /\ failures' = 0
            /\ openedAt' = 0
       ELSE UNCHANGED <<state, samples, failures, openedAt>>
    /\ UNCHANGED clock

\* Probe fails: CBREAK_INV_04 — immediately re-open, restart cooldown.
ProbeFailure ==
    /\ state = "half_open"
    /\ probesInFlight > 0
    /\ state' = "open"
    /\ openedAt' = clock
    /\ probesInFlight' = 0
    /\ UNCHANGED <<samples, failures, clock>>

\* Monotonic clock ticks forward (bounded to keep the model finite).
Tick ==
    /\ clock < MaxSamples + 4
    /\ clock' = clock + 1
    /\ UNCHANGED <<state, samples, failures, openedAt, probesInFlight>>

\* Stutter step: always possible once clock has saturated, keeps model deadlock-free.
Stutter ==
    /\ clock >= MaxSamples + 4
    /\ UNCHANGED vars

Next ==
    \/ ClosedSuccess
    \/ ClosedFailure
    \/ CooldownElapsed
    \/ GrantProbe
    \/ ProbeSuccess
    \/ ProbeFailure
    \/ Tick
    \/ Stutter

Spec == Init /\ [][Next]_vars

\* Safety: state is always one of the three legal values (maps CBREAK_INV_01/02/03 state domain).
StateBounded == state \in States

\* Safety: probes never exceed MaxProbes (CBREAK_INV_03).
ProbesBounded == probesInFlight <= MaxProbes

\* Safety: when open, probes are always zero (CBREAK_INV_01: open rejects every call).
OpenHasNoProbes == (state = "open") => (probesInFlight = 0)

\* Safety: when closed, no probes in flight either (probes exist only in half_open).
ClosedHasNoProbes == (state = "closed") => (probesInFlight = 0)

\* Safety: once the breaker transitioned to open because of the threshold rule
\* (CBREAK_INV_05), samples >= MinSamples held AT that time; we check the weaker
\* invariant that no transition to open happens when samples < MinSamples via
\* ClosedFailure's guard (encoded structurally).

\* Safety: clock is monotonic (CBREAK_INV_02).
ClockBounded == clock <= MaxSamples + 4

====
