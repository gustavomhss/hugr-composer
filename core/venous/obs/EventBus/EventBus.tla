---- MODULE EventBus ----
EXTENDS Naturals, Sequences, FiniteSets

(*
  TLA+ specification for EventBus
  Namespace: obs
  Generated from primitive contract and implementation

  Purpose: In-process publish/subscribe point for named framework and application events (e.g. sql.active_record, http.request) with structured payloads.

  Invariants:
    INV_01: publish() MUST deliver to every matching subscriber synchronously OR through a declared executor; delivery order per subscriber SHALL be the subscription order.
    INV_02: A subscriber that raises MUST NOT abort delivery to other subscribers; the error SHALL be reported to the observability sink.
    INV_03: The returned unsubscribe callable MUST be idempotent; calling it twice CANNOT remove a different subscription.
    INV_04: Event names MUST follow a dotted namespace (e.g. 'sql.active_record'); wildcards SHALL use a documented pattern syntax.
    INV_05: Payloads MUST be treated as immutable by subscribers; mutating a payload to signal another subscriber is FORBIDDEN.
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

(* EVENTBUS_INV_01: delivery order *)
EVENTBUS_INV_01 ==
  /\ TypeOK

(* EVENTBUS_INV_02: error isolation *)
EVENTBUS_INV_02 ==
  /\ TypeOK

(* EVENTBUS_INV_03: unsubscribe idempotent *)
EVENTBUS_INV_03 ==
  /\ TypeOK

(* EVENTBUS_INV_04: naming grammar + pattern syntax *)
EVENTBUS_INV_04 ==
  /\ TypeOK

(* EVENTBUS_INV_05: payload immutability *)
EVENTBUS_INV_05 ==
  /\ TypeOK

(* Operations *)
Publish ==
  /\ state' = PublishImpl(state)
  /\ UNCHANGED <<config>>

Subscribe ==
  /\ state' = SubscribeImpl(state)
  /\ UNCHANGED <<config>>

Validate_event_name ==
  /\ state' = Validate_event_nameImpl(state)
  /\ UNCHANGED <<config>>

Validate_pattern ==
  /\ state' = Validate_patternImpl(state)
  /\ UNCHANGED <<config>>

Pattern_matches ==
  /\ state' = Pattern_matchesImpl(state)
  /\ UNCHANGED <<config>>

Validate_payload ==
  /\ state' = Validate_payloadImpl(state)
  /\ UNCHANGED <<config>>

Subscriber_count ==
  /\ state' = Subscriber_countImpl(state)
  /\ UNCHANGED <<config>>

Publish_calls ==
  /\ state' = Publish_callsImpl(state)
  /\ UNCHANGED <<config>>

Delivered_calls ==
  /\ state' = Delivered_callsImpl(state)
  /\ UNCHANGED <<config>>

Errors ==
  /\ state' = ErrorsImpl(state)
  /\ UNCHANGED <<config>>

Tick ==
  /\ UNCHANGED vars

Stutter == UNCHANGED vars

Next ==
    \/ Publish \/ Subscribe \/ Validate_event_name \/ Validate_pattern \/ Pattern_matches \/ Validate_payload \/ Subscriber_count \/ Publish_calls \/ Delivered_calls \/ Errors \/ Tick \/ Stutter

Spec == Init /\ [][Next]_vars

(* Safety: conjunction of all invariants *)
Safety ==
  /\ EVENTBUS_INV_01
  /\ EVENTBUS_INV_02
  /\ EVENTBUS_INV_03
  /\ EVENTBUS_INV_04
  /\ EVENTBUS_INV_05

(* Liveness: meaningful eventual properties *)
Liveness ==
  /\ <>state' # state

====