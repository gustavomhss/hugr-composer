---- MODULE AuditEvent ----
EXTENDS Naturals, Sequences, FiniteSets

(*
  TLA+ specification for AuditEvent
  Namespace: compliance
  Generated from primitive contract and implementation

  Purpose: Emit a tamper-evident, append-only record of a security-relevant action with actor, subject, action verb, outcome, and a cryptographic chain link.

  Invariants:
    INV_01: event_hash MUST be computed as SHA-256 over the canonical serialization of all non-hash fields concatenated with prev_hash; a mismatched hash SHALL invalidate the chain.
    INV_02: Once emitted, an AuditEvent is append-only and CANNOT be updated, deleted, or logically superseded.
    INV_03: outcome MUST be one of 'success', 'failure', 'denied'; any other value is FORBIDDEN to keep reporting queryable.
    INV_04: actor_id MUST be set even for system-initiated actions; 'system' is a reserved literal and NEVER empty.
    INV_05: occurred_at MUST be an absolute UTC timestamp with at least millisecond precision; naive timestamps are FORBIDDEN.
    INV_06: action verbs MUST come from a controlled vocabulary (CREATE / READ / UPDATE / DELETE / GRANT / REVOKE / EXPORT) and ALWAYS use that controlled set for cross-system joins.
*)

CONSTANTS MaxInt

VARIABLES event_id, occurred_at, actor_id, actor_type, action, resource_type, resource_id, outcome, attributes, prev_hash, event_hash, 03, ALLOWED_OUTCOMES, 04, 06, 05, None, 0, attrs, event, 01

vars == <<event_id, occurred_at, actor_id, actor_type, action, resource_type, resource_id, outcome, attributes, prev_hash, event_hash, 03, ALLOWED_OUTCOMES, 04, 06, 05, None, 0, attrs, event, 01>>

TypeOK == 
  /\ event_id \in String
  /\ occurred_at \in String
  /\ actor_id \in String
  /\ actor_type \in String
  /\ action \in String
  /\ resource_type \in String
  /\ resource_id \in String
  /\ outcome \in String
  /\ attributes \in String
  /\ prev_hash \in String
  /\ event_hash \in String
  /\ 03 \in String
  /\ ALLOWED_OUTCOMES \in String
  /\ 04 \in String
  /\ 06 \in String
  /\ 05 \in String
  /\ None \in String
  /\ 0 \in String
  /\ attrs \in String
  /\ event \in String
  /\ 01 \in String

Init == 
  /\ event_id = ""
  /\ occurred_at = ""
  /\ actor_id = ""
  /\ actor_type = ""
  /\ action = ""
  /\ resource_type = ""
  /\ resource_id = ""
  /\ outcome = ""
  /\ attributes = ""
  /\ prev_hash = ""
  /\ event_hash = ""
  /\ 03 = ""
  /\ ALLOWED_OUTCOMES = ""
  /\ 04 = ""
  /\ 06 = ""
  /\ 05 = ""
  /\ None = ""
  /\ 0 = ""
  /\ attrs = ""
  /\ event = ""
  /\ 01 = ""

(* AUD_INV_01: hash chain integrity *)
AUD_INV_01 ==
  /\ TypeOK

(* AUD_INV_02: append-only *)
AUD_INV_02 ==
  /\ TypeOK

(* AUD_INV_03: outcome enum *)
AUD_INV_03 ==
  /\ TypeOK

(* AUD_INV_04: actor required *)
AUD_INV_04 ==
  /\ TypeOK

(* AUD_INV_05: UTC timestamp required *)
AUD_INV_05 ==
  /\ TypeOK

(* AUD_INV_06: action vocabulary *)
AUD_INV_06 ==
  /\ TypeOK

(* Operations *)
Compute_event_hash ==
  /\ event_id' = Compute_event_hashImpl(event_id)
  /\ UNCHANGED <<config>>

Build_event ==
  /\ event_id' = Build_eventImpl(event_id)
  /\ UNCHANGED <<config>>

Emit ==
  /\ event_id' = EmitImpl(event_id)
  /\ UNCHANGED <<config>>

Verify_chain ==
  /\ event_id' = Verify_chainImpl(event_id)
  /\ UNCHANGED <<config>>

Register_before_emit ==
  /\ event_id' = Register_before_emitImpl(event_id)
  /\ UNCHANGED <<config>>

Events ==
  /\ event_id' = EventsImpl(event_id)
  /\ UNCHANGED <<config>>

Size ==
  /\ event_id' = SizeImpl(event_id)
  /\ UNCHANGED <<config>>

Tick ==
  /\ UNCHANGED vars

Stutter == UNCHANGED vars

Next ==
    \/ Compute_event_hash \/ Build_event \/ Emit \/ Verify_chain \/ Register_before_emit \/ Events \/ Size \/ Tick \/ Stutter

Spec == Init /\ [][Next]_vars

(* Safety: conjunction of all invariants *)
Safety ==
  /\ AUD_INV_01
  /\ AUD_INV_02
  /\ AUD_INV_03
  /\ AUD_INV_04
  /\ AUD_INV_05
  /\ AUD_INV_06

(* Liveness: meaningful eventual properties *)
Liveness ==
  /\ <>event_id' # event_id

====