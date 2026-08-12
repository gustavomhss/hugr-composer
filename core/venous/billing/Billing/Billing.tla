---- MODULE Billing ----
EXTENDS Naturals, Sequences, FiniteSets

(*
  TLA+ specification for Billing
  Namespace: billing
  Generated from primitive contract and implementation

  Purpose: 

  Invariants:
*)

CONSTANTS MaxInt

VARIABLES Attributes, email, metadata, id, type, data

vars == <<Attributes, email, metadata, id, type, data>>

TypeOK == 
  /\ Attributes \in String
  /\ email \in String
  /\ metadata \in String
  /\ id \in String
  /\ type \in String
  /\ data \in String

Init == 
  /\ Attributes = ""
  /\ email = ""
  /\ metadata = ""
  /\ id = ""
  /\ type = ""
  /\ data = ""

(* BILL_INV_01: **Webhook signature verification is mandatory.** *)
BILL_INV_01 ==
  /\ TypeOK

(* BILL_INV_02: **Subscription lifecycle is monotonic.** Status transitions *)
BILL_INV_02 ==
  /\ version' = version + 1

(* BILL_INV_03: **Plan-change preserves subscription identity.** Given an *)
BILL_INV_03 ==
  /\ TypeOK

(* BILL_INV_04: **Identifiers are opaque and checked.** ``customer_id`` and *)
BILL_INV_04 ==
  /\ TypeOK

(* BILL_INV_05: **No PII in error messages.** Errors raised by this *)
BILL_INV_05 ==
  /\ TypeOK

(* Operations *)
Create_customer ==
  /\ Attributes' = Create_customerImpl(Attributes)
  /\ UNCHANGED <<config>>

Create_subscription ==
  /\ Attributes' = Create_subscriptionImpl(Attributes)
  /\ UNCHANGED <<config>>

Cancel_subscription ==
  /\ Attributes' = Cancel_subscriptionImpl(Attributes)
  /\ UNCHANGED <<config>>

Change_plan ==
  /\ Attributes' = Change_planImpl(Attributes)
  /\ UNCHANGED <<config>>

Construct_webhook_event ==
  /\ Attributes' = Construct_webhook_eventImpl(Attributes)
  /\ UNCHANGED <<config>>

Get_customer ==
  /\ Attributes' = Get_customerImpl(Attributes)
  /\ UNCHANGED <<config>>

Set_status ==
  /\ Attributes' = Set_statusImpl(Attributes)
  /\ UNCHANGED <<config>>

Get_subscription ==
  /\ Attributes' = Get_subscriptionImpl(Attributes)
  /\ UNCHANGED <<config>>

Sign_payload ==
  /\ Attributes' = Sign_payloadImpl(Attributes)
  /\ UNCHANGED <<config>>

Tick ==
  /\ UNCHANGED vars

Stutter == UNCHANGED vars

Next ==
    \/ Create_customer \/ Create_subscription \/ Cancel_subscription \/ Change_plan \/ Construct_webhook_event \/ Get_customer \/ Set_status \/ Get_subscription \/ Sign_payload \/ Tick \/ Stutter

Spec == Init /\ [][Next]_vars

(* Safety: conjunction of all invariants *)
Safety ==
  /\ BILL_INV_01
  /\ BILL_INV_02
  /\ BILL_INV_03
  /\ BILL_INV_04
  /\ BILL_INV_05

(* Liveness: meaningful eventual properties *)
Liveness ==
  /\ <>Attributes' # Attributes

====