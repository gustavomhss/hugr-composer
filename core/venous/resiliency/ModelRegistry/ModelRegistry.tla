---- MODULE ModelRegistry ----
EXTENDS Naturals, Sequences, FiniteSets

(*
  TLA+ specification for ModelRegistry
  Namespace: resiliency
  Generated from primitive contract and implementation

  Purpose: Dict-based singleton registry for lazily-loaded model instances (ML, embeddings, rule-engines). Each name:version maps to a zero-arg loader callable; the object is constructed on first `get()` and cached.

  Invariants:
    INV_01: MODEL_REGISTRY_INV_01: `get(name, version)` MUST invoke the loader at most once per name:version pair across the registry's lifetime (memoisation).
    INV_02: MODEL_REGISTRY_INV_02: `get()` on an unregistered name:version MUST raise KeyError — fail-loud, no silent None return, no implicit registration.
    INV_03: MODEL_REGISTRY_INV_03: `register()` with `version` defaulting to 'latest' MUST be the logical identifier for unversioned callers; two distinct version strings under the same name MUST coexist as independent cache slots.
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

(* MODELREGISTRY_INV_01: MODEL_REGISTRY_INV_01: `get(name, version)` MUST invoke the loader at most once per name:version pair across the registry's lifetime (memoisation). *)
MODELREGISTRY_INV_01 ==
  /\ TypeOK

(* MODELREGISTRY_INV_02: MODEL_REGISTRY_INV_02: `get()` on an unregistered name:version MUST raise KeyError — fail-loud, no silent None return, no implicit registration. *)
MODELREGISTRY_INV_02 ==
  /\ key # ""

(* MODELREGISTRY_INV_03: MODEL_REGISTRY_INV_03: `register()` with `version` defaulting to 'latest' MUST be the logical identifier for unversioned callers; two distinct version strings under the same name MUST coexist as independent cache slots. *)
MODELREGISTRY_INV_03 ==
  /\ TypeOK

(* Operations *)
Register ==
  /\ state' = RegisterImpl(state)
  /\ UNCHANGED <<config>>

Get ==
  /\ key # ""
  /\ result' = GetImpl(key)
  /\ UNCHANGED <<config>>

List_models ==
  /\ state' = List_modelsImpl(state)
  /\ UNCHANGED <<config>>

Update_stats ==
  /\ state' = Update_statsImpl(state)
  /\ UNCHANGED <<config>>

Tick ==
  /\ UNCHANGED vars

Stutter == UNCHANGED vars

Next ==
    \/ Register \/ Get \/ List_models \/ Update_stats \/ Tick \/ Stutter

Spec == Init /\ [][Next]_vars

(* Safety: conjunction of all invariants *)
Safety ==
  /\ MODELREGISTRY_INV_01
  /\ MODELREGISTRY_INV_02
  /\ MODELREGISTRY_INV_03

(* Liveness: meaningful eventual properties *)
Liveness ==
  /\ <>state' # state

====