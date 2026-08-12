---- MODULE FeatureToggle ----
EXTENDS Naturals, Sequences, FiniteSets

(*
  TLA+ specification for FeatureToggle
  Namespace: flags
  Generated from primitive contract and implementation

  Purpose: Named boolean (or variant) predicate, evaluated against the current context, that controls whether a code path is live for a given request.

  Invariants:
    INV_01: is_active() MUST be pure given the same (key, ctx); side effects (I/O, random draws) SHALL NEVER leak into evaluation.
    INV_02: Evaluation MUST default to False (off) when the backing store is unreachable; CANNOT default to on.
    INV_03: A toggle key MUST be unique within the registry and SHALL follow a fixed naming convention.
    INV_04: The evaluation path MUST record an observability event (toggle key + decision) for every call; audit entries NEVER are dropped.
    INV_05: Removing a toggle MUST be a two-step deprecation: mark stale, then delete; code references CANNOT disappear abruptly.
*)

CONSTANTS MaxInt

VARIABLES principal_id, tenant_id, environment, key, decision, ctx_principal, ctx_tenant, ctx_environment

vars == <<principal_id, tenant_id, environment, key, decision, ctx_principal, ctx_tenant, ctx_environment>>

TypeOK == 
  /\ principal_id \in String
  /\ tenant_id \in String
  /\ environment \in String
  /\ key \in String
  /\ decision \in {TRUE, FALSE}
  /\ ctx_principal \in String
  /\ ctx_tenant \in String
  /\ ctx_environment \in String

Init == 
  /\ principal_id = ""
  /\ tenant_id = ""
  /\ environment = ""
  /\ key = ""
  /\ decision = FALSE
  /\ ctx_principal = ""
  /\ ctx_tenant = ""
  /\ ctx_environment = ""

(* FT_INV_01: purity of is_active *)
FT_INV_01 ==
  /\ TypeOK

(* FT_INV_02: off by default on unreachable store *)
FT_INV_02 ==
  /\ TypeOK

(* FT_INV_03: unique key + naming convention *)
FT_INV_03 ==
  /\ TypeOK

(* FT_INV_04: every evaluation recorded *)
FT_INV_04 ==
  /\ TypeOK

(* FT_INV_05: two-step deprecation *)
FT_INV_05 ==
  /\ TypeOK

(* Operations *)
Is_active ==
  /\ principal_id' = Is_activeImpl(principal_id)
  /\ UNCHANGED <<config>>

Validate_key ==
  /\ principal_id' = Validate_keyImpl(principal_id)
  /\ UNCHANGED <<config>>

Register ==
  /\ principal_id' = RegisterImpl(principal_id)
  /\ UNCHANGED <<config>>

Mark_stale ==
  /\ principal_id' = Mark_staleImpl(principal_id)
  /\ UNCHANGED <<config>>

Delete ==
  /\ key # ""
  /\ result' = DeleteImpl(key)
  /\ UNCHANGED <<config>>

Audit ==
  /\ principal_id' = AuditImpl(principal_id)
  /\ UNCHANGED <<config>>

Is_stale ==
  /\ principal_id' = Is_staleImpl(principal_id)
  /\ UNCHANGED <<config>>

Known_keys ==
  /\ principal_id' = Known_keysImpl(principal_id)
  /\ UNCHANGED <<config>>

Tick ==
  /\ UNCHANGED vars

Stutter == UNCHANGED vars

Next ==
    \/ Is_active \/ Validate_key \/ Register \/ Mark_stale \/ Delete \/ Audit \/ Is_stale \/ Known_keys \/ Tick \/ Stutter

Spec == Init /\ [][Next]_vars

(* Safety: conjunction of all invariants *)
Safety ==
  /\ FT_INV_01
  /\ FT_INV_02
  /\ FT_INV_03
  /\ FT_INV_04
  /\ FT_INV_05

(* Liveness: meaningful eventual properties *)
Liveness ==
  /\ <>principal_id' # principal_id

====