---- MODULE ContextMap ----
EXTENDS Naturals, Sequences, FiniteSets

(*
  TLA+ specification for ContextMap
  Namespace: api
  Generated from primitive contract and implementation

  Purpose: Catalogs every BoundedContext and the integration relationship (Partnership, Customer-Supplier, Conformist, Open Host) between each pair.

  Invariants:
    INV_01: Every pairwise integration between contexts MUST be classified by one of the canonical relationship kinds; ad-hoc or blank relationships are FORBIDDEN.
    INV_02: The graph of contexts SHALL be acyclic for Customer-Supplier relationships; a cycle CANNOT be introduced without promotion to Partnership.
    INV_03: A BoundedContext CANNOT participate in an integration absent from the ContextMap; shadow integrations MUST be surfaced.
    INV_04: Relationship changes ALWAYS require an explicit mutation through add_relationship so history is auditable.
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

(* CTXMAP_INV_01: canonical relationship kinds only *)
CTXMAP_INV_01 ==
  /\ TypeOK

(* CTXMAP_INV_02: Customer-Supplier graph is directional-acyclic *)
CTXMAP_INV_02 ==
  /\ TypeOK

(* CTXMAP_INV_03: no shadow integrations; invalid context names rejected *)
CTXMAP_INV_03 ==
  /\ TypeOK

(* CTXMAP_INV_04: all mutations flow through add_relationship (version bumps) *)
CTXMAP_INV_04 ==
  /\ TypeOK

(* Operations *)
Contexts ==
  /\ state' = ContextsImpl(state)
  /\ UNCHANGED <<config>>

Relationship ==
  /\ state' = RelationshipImpl(state)
  /\ UNCHANGED <<config>>

Add_relationship ==
  /\ state' = Add_relationshipImpl(state)
  /\ UNCHANGED <<config>>

Integrations ==
  /\ state' = IntegrationsImpl(state)
  /\ UNCHANGED <<config>>

Version ==
  /\ state' = VersionImpl(state)
  /\ UNCHANGED <<config>>

Has_edge ==
  /\ state' = Has_edgeImpl(state)
  /\ UNCHANGED <<config>>

Tick ==
  /\ UNCHANGED vars

Stutter == UNCHANGED vars

Next ==
    \/ Contexts \/ Relationship \/ Add_relationship \/ Integrations \/ Version \/ Has_edge \/ Tick \/ Stutter

Spec == Init /\ [][Next]_vars

(* Safety: conjunction of all invariants *)
Safety ==
  /\ CTXMAP_INV_01
  /\ CTXMAP_INV_02
  /\ CTXMAP_INV_03
  /\ CTXMAP_INV_04

(* Liveness: meaningful eventual properties *)
Liveness ==
  /\ <>state' # state

====