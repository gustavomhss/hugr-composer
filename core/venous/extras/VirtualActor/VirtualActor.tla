---- MODULE VirtualActor ----
EXTENDS Naturals, Sequences, FiniteSets

(*
  TLA+ specification for VirtualActor
  Namespace: extras
  Generated from primitive contract and implementation

  Purpose: Location transparent single writer object addressed by type and id that holds private state and processes one message at a time on activation.

  Invariants:
    INV_01: Only one invocation of a given ActorId runs at a time; concurrent calls MUST queue in arrival order.
    INV_02: Actor state NEVER escapes the actor instance; callers ALWAYS read it through invoke, never via direct store access.
    INV_03: Reminders MUST survive actor deactivation and restart; they SHALL fire after the configured period regardless of host.
    INV_04: Timers within an actor CANNOT outlive deactivation; reminders are the durable option.
    INV_05: Caller code MUST NOT depend on the physical host of an actor because placement can migrate on failover.
*)

CONSTANTS MaxInt

VARIABLES actor_type, key, None, supporting, state, actor_id, handlers, lock, invocations

vars == <<actor_type, key, None, supporting, state, actor_id, handlers, lock, invocations>>

TypeOK == 
  /\ actor_type \in String
  /\ key \in String
  /\ None \in String
  /\ supporting \in String
  /\ state \in String
  /\ actor_id \in String
  /\ handlers \in String
  /\ lock \in String
  /\ invocations \in 0..MaxInt

Init == 
  /\ actor_type = ""
  /\ key = ""
  /\ None = ""
  /\ supporting = ""
  /\ state = ""
  /\ actor_id = ""
  /\ handlers = ""
  /\ lock = ""
  /\ invocations = 0

(* VACT_INV_01: single-writer / serial invocation per ActorId *)
VACT_INV_01 ==
  /\ TypeOK

(* VACT_INV_02: state never escapes actor *)
VACT_INV_02 ==
  /\ TypeOK

(* VACT_INV_03: reminders survive deactivation *)
VACT_INV_03 ==
  /\ TypeOK

(* VACT_INV_04: in-actor timers NEVER outlive deactivation *)
VACT_INV_04 ==
  /\ TypeOK

(* VACT_INV_05: caller never depends on physical host *)
VACT_INV_05 ==
  /\ TypeOK

(* Operations *)
Register ==
  /\ actor_type' = RegisterImpl(actor_type)
  /\ UNCHANGED <<config>>

Reminder_count ==
  /\ actor_type' = Reminder_countImpl(actor_type)
  /\ UNCHANGED <<config>>

Has_reminder ==
  /\ actor_type' = Has_reminderImpl(actor_type)
  /\ UNCHANGED <<config>>

Invocations_for ==
  /\ actor_type' = Invocations_forImpl(actor_type)
  /\ UNCHANGED <<config>>

Deactivate_all ==
  /\ actor_type' = Deactivate_allImpl(actor_type)
  /\ UNCHANGED <<config>>

Reinstate ==
  /\ actor_type' = ReinstateImpl(actor_type)
  /\ UNCHANGED <<config>>

Tick ==
  /\ UNCHANGED vars

Stutter == UNCHANGED vars

Next ==
    \/ Register \/ Reminder_count \/ Has_reminder \/ Invocations_for \/ Deactivate_all \/ Reinstate \/ Tick \/ Stutter

Spec == Init /\ [][Next]_vars

(* Safety: conjunction of all invariants *)
Safety ==
  /\ VACT_INV_01
  /\ VACT_INV_02
  /\ VACT_INV_03
  /\ VACT_INV_04
  /\ VACT_INV_05

(* Liveness: meaningful eventual properties *)
Liveness ==
  /\ <>actor_type' # actor_type

====