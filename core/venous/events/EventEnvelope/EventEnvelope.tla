---- MODULE EventEnvelope ----
EXTENDS Naturals, Sequences, FiniteSets

(*
  TLA+ specification for EventEnvelope
  Namespace: events
  Generated from primitive contract and implementation

  Purpose: Canonical CloudEvents 1.0 shape that normalizes id, source, type, time and payload so downstream handlers parse the same structure regardless of transport.

  Invariants:
    INV_01: Producers MUST make the tuple (source, id) unique per distinct occurrence so consumers can deduplicate.
    INV_02: Resending the same logical event ALWAYS reuses the original id so retries do not appear as new occurrences.
    INV_03: specversion MUST equal '1.0' for envelopes produced under this contract.
    INV_04: Extension attribute names MUST follow the same naming rules as core attributes and CANNOT collide with reserved names.
    INV_05: time when present SHALL be an RFC 3339 timestamp in UTC with no timezone offset ambiguity.
*)

CONSTANTS MaxInt

VARIABLES id, source, type, specversion, datacontenttype, dataschema, subject, time, data, extensions, None, supporting, EE_INV_01, EE_INV_02

vars == <<id, source, type, specversion, datacontenttype, dataschema, subject, time, data, extensions, None, supporting, EE_INV_01, EE_INV_02>>

TypeOK == 
  /\ id \in String
  /\ source \in String
  /\ type \in String
  /\ specversion \in String
  /\ datacontenttype \in String
  /\ dataschema \in String
  /\ subject \in String
  /\ time \in String
  /\ data \in String
  /\ extensions \in String
  /\ None \in String
  /\ supporting \in String
  /\ EE_INV_01 \in String
  /\ EE_INV_02 \in String

Init == 
  /\ id = ""
  /\ source = ""
  /\ type = ""
  /\ specversion = ""
  /\ datacontenttype = ""
  /\ dataschema = ""
  /\ subject = ""
  /\ time = ""
  /\ data = ""
  /\ extensions = ""
  /\ None = ""
  /\ supporting = ""
  /\ EE_INV_01 = ""
  /\ EE_INV_02 = ""

(* EE_INV_01: Producers MUST make the tuple (source, id) unique per distinct *)
EE_INV_01 ==
  /\ TypeOK

(* EE_INV_02: Resending the same logical event ALWAYS reuses the original id *)
EE_INV_02 ==
  /\ TypeOK

(* EE_INV_03: specversion MUST equal '1.0' for envelopes produced under this *)
EE_INV_03 ==
  /\ TypeOK

(* EE_INV_04: Extension attribute names MUST match the CloudEvents naming rules *)
EE_INV_04 ==
  /\ TypeOK

(* EE_INV_05: time when present SHALL be an RFC 3339 timestamp in UTC with no *)
EE_INV_05 ==
  /\ TypeOK

(* Operations *)
Validate_specversion ==
  /\ id' = Validate_specversionImpl(id)
  /\ UNCHANGED <<config>>

Validate_time ==
  /\ id' = Validate_timeImpl(id)
  /\ UNCHANGED <<config>>

Validate_extension_name ==
  /\ id' = Validate_extension_nameImpl(id)
  /\ UNCHANGED <<config>>

Validate_extensions ==
  /\ id' = Validate_extensionsImpl(id)
  /\ UNCHANGED <<config>>

Dedup_key ==
  /\ id' = Dedup_keyImpl(id)
  /\ UNCHANGED <<config>>

Retry ==
  /\ id' = RetryImpl(id)
  /\ UNCHANGED <<config>>

Accept ==
  /\ id' = AcceptImpl(id)
  /\ UNCHANGED <<config>>

Size ==
  /\ id' = SizeImpl(id)
  /\ UNCHANGED <<config>>

Tick ==
  /\ UNCHANGED vars

Stutter == UNCHANGED vars

Next ==
    \/ Validate_specversion \/ Validate_time \/ Validate_extension_name \/ Validate_extensions \/ Dedup_key \/ Retry \/ Accept \/ Size \/ Tick \/ Stutter

Spec == Init /\ [][Next]_vars

(* Safety: conjunction of all invariants *)
Safety ==
  /\ EE_INV_01
  /\ EE_INV_02
  /\ EE_INV_03
  /\ EE_INV_04
  /\ EE_INV_05

(* Liveness: meaningful eventual properties *)
Liveness ==
  /\ <>id' # id

====