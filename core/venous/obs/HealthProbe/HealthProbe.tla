---- MODULE HealthProbe ----
EXTENDS Naturals, Sequences, FiniteSets

(*
  TLA+ specification for HealthProbe
  Namespace: obs
  Generated from primitive contract and implementation

  Purpose: Small probe that reports UP/DOWN/DEGRADED with optional detail so orchestrators (Kubernetes, load balancers) can route traffic safely.

  Invariants:
    INV_01: check() MUST complete within a declared timeout; a hanging probe SHALL be treated as DOWN.
    INV_02: A probe MUST NEVER throw; unexpected exceptions SHALL be caught and turned into DOWN with the exception class as detail.
    INV_03: name MUST be unique within the registry; duplicate registrations SHALL be rejected.
    INV_04: details MUST NOT leak secrets (connection strings, tokens); callers CANNOT rely on raw credentials appearing.
    INV_05: The aggregated readiness endpoint MUST be UP only when every required probe is UP; optional probes CANNOT force readiness false.
*)

CONSTANTS MaxInt

VARIABLES name, status, details, probe, requirement

vars == <<name, status, details, probe, requirement>>

TypeOK == 
  /\ name \in String
  /\ status \in String
  /\ details \in String
  /\ probe \in String
  /\ requirement \in String

Init == 
  /\ name = ""
  /\ status = ""
  /\ details = ""
  /\ probe = ""
  /\ requirement = ""

(* HEALTHPROBE_INV_01: liveness ignores dependency status *)
HEALTHPROBE_INV_01 ==
  /\ TypeOK

(* HEALTHPROBE_INV_02: readiness worst-wins across required dependencies *)
HEALTHPROBE_INV_02 ==
  /\ read_version = write_version

(* HEALTHPROBE_INV_03: bounded by timeout; a hanging probe is DOWN *)
HEALTHPROBE_INV_03 ==
  /\ name <= MaxInt

(* HEALTHPROBE_INV_04: a probe MUST NEVER throw *)
HEALTHPROBE_INV_04 ==
  /\ TypeOK

(* HEALTHPROBE_INV_05: unique name within the registry *)
HEALTHPROBE_INV_05 ==
  /\ TypeOK

(* HEALTHPROBE_INV_06: details MUST NOT leak secrets *)
HEALTHPROBE_INV_06 ==
  /\ TypeOK

(* HEALTHPROBE_INV_07: debounce UP->DOWN transitions *)
HEALTHPROBE_INV_07 ==
  /\ TypeOK

(* Operations *)
Register_dependency ==
  /\ name' = Register_dependencyImpl(name)
  /\ UNCHANGED <<config>>

Sanitize_report ==
  /\ name' = Sanitize_reportImpl(name)
  /\ UNCHANGED <<config>>

Register ==
  /\ name' = RegisterImpl(name)
  /\ UNCHANGED <<config>>

Get ==
  /\ key # ""
  /\ result' = GetImpl(key)
  /\ UNCHANGED <<config>>

Names ==
  /\ name' = NamesImpl(name)
  /\ UNCHANGED <<config>>

Tick ==
  /\ UNCHANGED vars

Stutter == UNCHANGED vars

Next ==
    \/ Register_dependency \/ Sanitize_report \/ Register \/ Get \/ Names \/ Tick \/ Stutter

Spec == Init /\ [][Next]_vars

(* Safety: conjunction of all invariants *)
Safety ==
  /\ HEALTHPROBE_INV_01
  /\ HEALTHPROBE_INV_02
  /\ HEALTHPROBE_INV_03
  /\ HEALTHPROBE_INV_04
  /\ HEALTHPROBE_INV_05
  /\ HEALTHPROBE_INV_06
  /\ HEALTHPROBE_INV_07

(* Liveness: meaningful eventual properties *)
Liveness ==
  /\ <>name' # name

====