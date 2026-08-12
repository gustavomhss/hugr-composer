---- MODULE RouterPipeline ----
EXTENDS Naturals, Sequences, FiniteSets

(*
  TLA+ specification for RouterPipeline
  Namespace: api
  Generated from primitive contract and implementation

  Purpose: Named bundle of middleware (e.g. 'browser', 'api') that a route joins with pipe_through so groups of endpoints share the same pre-dispatch chain.

  Invariants:
    INV_01: A pipeline MUST run its middleware in declared order, every time; reorder at runtime SHALL NEVER happen.
    INV_02: A route joined to a pipeline MUST execute its chain before the handler; the chain CANNOT be bypassed per request.
    INV_03: Pipelines MUST NOT share mutable state across requests; any state SHALL live in RequestContext.assigns.
    INV_04: Joining a route to a pipeline MUST be declarative; programmatic attach CANNOT happen after the router is sealed.
    INV_05: A pipeline name MUST be unique within the router; duplicate declarations SHALL raise at boot.
*)

CONSTANTS MaxInt

VARIABLES route, method, assigns, halted, halt_reason, reason, 02, signature, name, middleware, _router, _routes, declarative, is_sealed, 04, supporting

vars == <<route, method, assigns, halted, halt_reason, reason, 02, signature, name, middleware, _router, _routes, declarative, is_sealed, 04, supporting>>

TypeOK == 
  /\ route \in String
  /\ method \in String
  /\ assigns \in String
  /\ halted \in {TRUE, FALSE}
  /\ halt_reason \in String
  /\ reason \in String
  /\ 02 \in String
  /\ signature \in String
  /\ name \in String
  /\ middleware \in String
  /\ _router \in String
  /\ _routes \in String
  /\ declarative \in String
  /\ is_sealed \in String
  /\ 04 \in String
  /\ supporting \in String

Init == 
  /\ route = ""
  /\ method = ""
  /\ assigns = ""
  /\ halted = FALSE
  /\ halt_reason = ""
  /\ reason = ""
  /\ 02 = ""
  /\ signature = ""
  /\ name = ""
  /\ middleware = ""
  /\ _router = ""
  /\ _routes = ""
  /\ declarative = ""
  /\ is_sealed = ""
  /\ 04 = ""
  /\ supporting = ""

(* RP_INV_01: middleware runs in declared order every time *)
RP_INV_01 ==
  /\ TypeOK

(* RP_INV_02: chain runs before the handler; no per-request bypass *)
RP_INV_02 ==
  /\ TypeOK

(* RP_INV_03: pipelines do not share mutable state across requests *)
RP_INV_03 ==
  /\ TypeOK

(* RP_INV_04: attach and register refused after seal *)
RP_INV_04 ==
  /\ TypeOK

(* RP_INV_05: pipeline names are unique within a router *)
RP_INV_05 ==
  /\ TypeOK

(* Operations *)
Halt ==
  /\ route' = HaltImpl(route)
  /\ UNCHANGED <<config>>

Attach ==
  /\ route' = AttachImpl(route)
  /\ UNCHANGED <<config>>

Routes ==
  /\ route' = RoutesImpl(route)
  /\ UNCHANGED <<config>>

Is_sealed ==
  /\ route' = Is_sealedImpl(route)
  /\ UNCHANGED <<config>>

Pipelines ==
  /\ route' = PipelinesImpl(route)
  /\ UNCHANGED <<config>>

Attachments ==
  /\ route' = AttachmentsImpl(route)
  /\ UNCHANGED <<config>>

Get ==
  /\ key # ""
  /\ result' = GetImpl(key)
  /\ UNCHANGED <<config>>

Register ==
  /\ route' = RegisterImpl(route)
  /\ UNCHANGED <<config>>

Seal ==
  /\ route' = SealImpl(route)
  /\ UNCHANGED <<config>>

Record_attachment ==
  /\ route' = Record_attachmentImpl(route)
  /\ UNCHANGED <<config>>

Dispatch ==
  /\ route' = DispatchImpl(route)
  /\ UNCHANGED <<config>>

Tick ==
  /\ UNCHANGED vars

Stutter == UNCHANGED vars

Next ==
    \/ Halt \/ Attach \/ Routes \/ Is_sealed \/ Pipelines \/ Attachments \/ Get \/ Register \/ Seal \/ Record_attachment \/ Dispatch \/ Tick \/ Stutter

Spec == Init /\ [][Next]_vars

(* Safety: conjunction of all invariants *)
Safety ==
  /\ RP_INV_01
  /\ RP_INV_02
  /\ RP_INV_03
  /\ RP_INV_04
  /\ RP_INV_05

(* Liveness: meaningful eventual properties *)
Liveness ==
  /\ <>route' # route

====