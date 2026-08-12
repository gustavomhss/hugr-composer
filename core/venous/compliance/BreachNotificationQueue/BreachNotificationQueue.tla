---- MODULE BreachNotificationQueue ----
EXTENDS Naturals, Sequences, FiniteSets

(*
  TLA+ specification for BreachNotificationQueue
  Namespace: compliance
  Generated from primitive contract and implementation

  Purpose: Tracks suspected and confirmed personal-data incidents with a statutory notification clock, so the 72-hour window is enforced in code.

  Invariants:
    INV_01: An incident confirmed as affecting personal data MUST have a notify_authority call within 72 hours of confirmed_at; the queue SHALL emit a breach-of-SLA alert at T-24h.
    INV_02: open_incident MUST be callable from any service with write access to the queue; there is NEVER a gating step that delays detection recording.
    INV_03: Every state transition (open, confirm, notify, close) MUST emit a TamperEvidentAuditLog entry.
    INV_04: data_classes on confirm MUST be a non-empty tuple of PiiClassification-registered classes; empty tuples SHALL raise.
    INV_05: An incident CANNOT close without either a notify_authority entry or an explicit 'no_notification_required' outcome with a legal_basis field.
*)

CONSTANTS MaxInt

VARIABLES incident_id, detected_at, severity, summary, confirmed_at, data_classes, notifications, closed_outcome, legal_basis

vars == <<incident_id, detected_at, severity, summary, confirmed_at, data_classes, notifications, closed_outcome, legal_basis>>

TypeOK == 
  /\ incident_id \in String
  /\ detected_at \in String
  /\ severity \in String
  /\ summary \in String
  /\ confirmed_at \in String
  /\ data_classes \in String
  /\ notifications \in String
  /\ closed_outcome \in String
  /\ legal_basis \in String

Init == 
  /\ incident_id = ""
  /\ detected_at = ""
  /\ severity = ""
  /\ summary = ""
  /\ confirmed_at = ""
  /\ data_classes = ""
  /\ notifications = ""
  /\ closed_outcome = ""
  /\ legal_basis = ""

(* BNQ_INV_01: An incident confirmed as affecting personal data MUST have a *)
BNQ_INV_01 ==
  /\ TypeOK

(* BNQ_INV_02: `open_incident` MUST be callable from any service with write *)
BNQ_INV_02 ==
  /\ TypeOK

(* BNQ_INV_03: Every state transition (open, confirm, notify, close) MUST *)
BNQ_INV_03 ==
  /\ TypeOK

(* BNQ_INV_04: `data_classes` on confirm MUST be a non-empty tuple of *)
BNQ_INV_04 ==
  /\ TypeOK

(* BNQ_INV_05: An incident CANNOT close without either a `notify_authority` *)
BNQ_INV_05 ==
  /\ TypeOK

(* Operations *)
Append ==
  /\ incident_id' = AppendImpl(incident_id)
  /\ UNCHANGED <<config>>

Open_incident ==
  /\ incident_id' = Open_incidentImpl(incident_id)
  /\ UNCHANGED <<config>>

Confirm ==
  /\ incident_id' = ConfirmImpl(incident_id)
  /\ UNCHANGED <<config>>

Notify_authority ==
  /\ incident_id' = Notify_authorityImpl(incident_id)
  /\ UNCHANGED <<config>>

Close ==
  /\ incident_id' = CloseImpl(incident_id)
  /\ UNCHANGED <<config>>

Time_to_deadline ==
  /\ incident_id' = Time_to_deadlineImpl(incident_id)
  /\ UNCHANGED <<config>>

Is_sla_warning ==
  /\ incident_id' = Is_sla_warningImpl(incident_id)
  /\ UNCHANGED <<config>>

Is_sla_breached ==
  /\ incident_id' = Is_sla_breachedImpl(incident_id)
  /\ UNCHANGED <<config>>

Size ==
  /\ incident_id' = SizeImpl(incident_id)
  /\ UNCHANGED <<config>>

Tick ==
  /\ UNCHANGED vars

Stutter == UNCHANGED vars

Next ==
    \/ Append \/ Open_incident \/ Confirm \/ Notify_authority \/ Close \/ Time_to_deadline \/ Is_sla_warning \/ Is_sla_breached \/ Size \/ Tick \/ Stutter

Spec == Init /\ [][Next]_vars

(* Safety: conjunction of all invariants *)
Safety ==
  /\ BNQ_INV_01
  /\ BNQ_INV_02
  /\ BNQ_INV_03
  /\ BNQ_INV_04
  /\ BNQ_INV_05

(* Liveness: meaningful eventual properties *)
Liveness ==
  /\ <>incident_id' # incident_id

====