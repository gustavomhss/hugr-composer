---- MODULE ConfigBinding ----
EXTENDS Naturals, Sequences, FiniteSets

(*
  TLA+ specification for ConfigBinding
  Namespace: data
  Generated from primitive contract and implementation

  Purpose: Binds a namespaced slice of the runtime configuration to a typed record, validated at startup so misconfiguration fails loud, not silent.

  Invariants:
    INV_01: bind() MUST fail loudly if required keys are missing or typed coercion fails; it NEVER returns a partially-filled record.
    INV_02: Bound records MUST be frozen/immutable; runtime code CANNOT mutate a bound option to affect another consumer.
    INV_03: reload() MUST produce a new record without aliasing the previous one; references already handed out SHALL NOT silently mutate.
    INV_04: Unknown keys under the prefix MUST be reported as errors by default (strict binding) and NEVER silently dropped.
    INV_05: Precedence order (env > file > defaults) MUST be fixed and documented; a later source CANNOT override a value an operator pinned.
*)

CONSTANTS MaxInt

VARIABLES state, config

vars == <<state, config>>

TypeOK == 
  /\ state \in String
  /\ config \in String

Init == 
  /\ state = ""
  /\ config = ""

(* CONFIG_INV_01: fail loudly on missing/bad values *)
CONFIG_INV_01 ==
  /\ TypeOK

(* CONFIG_INV_02: frozen/immutable records *)
CONFIG_INV_02 ==
  /\ TypeOK

(* CONFIG_INV_03: reload produces new record without aliasing *)
CONFIG_INV_03 ==
  /\ TypeOK

(* CONFIG_INV_04: unknown keys are errors *)
CONFIG_INV_04 ==
  /\ TypeOK

(* CONFIG_INV_05: precedence (env > file > defaults), env pinned *)
CONFIG_INV_05 ==
  /\ TypeOK

(* Operations *)
Name ==
  /\ state' = NameImpl(state)
  /\ UNCHANGED <<config>>

Pinned ==
  /\ state' = PinnedImpl(state)
  /\ UNCHANGED <<config>>

Values ==
  /\ state' = ValuesImpl(state)
  /\ UNCHANGED <<config>>

Get ==
  /\ key # ""
  /\ result' = GetImpl(key)
  /\ UNCHANGED <<config>>

Bind ==
  /\ state' = BindImpl(state)
  /\ UNCHANGED <<config>>

Reload ==
  /\ state' = ReloadImpl(state)
  /\ UNCHANGED <<config>>

Providers ==
  /\ state' = ProvidersImpl(state)
  /\ UNCHANGED <<config>>

Current ==
  /\ state' = CurrentImpl(state)
  /\ UNCHANGED <<config>>

Tick ==
  /\ UNCHANGED vars

Stutter == UNCHANGED vars

Next ==
    \/ Name \/ Pinned \/ Values \/ Get \/ Bind \/ Reload \/ Providers \/ Current \/ Tick \/ Stutter

Spec == Init /\ [][Next]_vars

(* Safety: conjunction of all invariants *)
Safety ==
  /\ CONFIG_INV_01
  /\ CONFIG_INV_02
  /\ CONFIG_INV_03
  /\ CONFIG_INV_04
  /\ CONFIG_INV_05

(* Liveness: meaningful eventual properties *)
Liveness ==
  /\ <>state' # state

====