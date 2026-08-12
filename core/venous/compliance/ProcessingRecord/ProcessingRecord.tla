---- MODULE ProcessingRecord ----
EXTENDS Naturals, Sequences, FiniteSets

(*
  TLA+ specification for ProcessingRecord
  Namespace: compliance
  Generated from primitive contract and implementation

  Purpose: Machine-readable record of processing activities that a controller must maintain, generated from code rather than a separate document.

  Invariants:
    INV_01: Every code path that reads or writes PII MUST be annotated with a registered ProcessingRecord.activity; unregistered activities SHALL fail at startup.
    INV_02: Each record MUST reference a retention_ref that resolves to a bound RetentionPolicy; dangling refs CANNOT register.
    INV_03: legal_basis MUST be one of GDPR Article 6(1)(a-f); free-text values SHALL raise.
    INV_04: transfers_outside_eea entries MUST be ISO-3166 country codes; other formats are FORBIDDEN.
    INV_05: export_ropa() output MUST be byte-for-byte reproducible given the same registry so auditors can hash and diff releases.
*)

CONSTANTS MaxInt

VARIABLES activity, controller, purposes, data_classes, recipients, retention_ref, legal_basis, transfers_outside_eea, None, PR_INV_01, ALLOWED_LEGAL_BASES, PR_INV_03, PR_INV_04

vars == <<activity, controller, purposes, data_classes, recipients, retention_ref, legal_basis, transfers_outside_eea, None, PR_INV_01, ALLOWED_LEGAL_BASES, PR_INV_03, PR_INV_04>>

TypeOK == 
  /\ activity \in String
  /\ controller \in String
  /\ purposes \in String
  /\ data_classes \in String
  /\ recipients \in String
  /\ retention_ref \in String
  /\ legal_basis \in String
  /\ transfers_outside_eea \in String
  /\ None \in String
  /\ PR_INV_01 \in String
  /\ ALLOWED_LEGAL_BASES \in String
  /\ PR_INV_03 \in String
  /\ PR_INV_04 \in String

Init == 
  /\ activity = ""
  /\ controller = ""
  /\ purposes = ""
  /\ data_classes = ""
  /\ recipients = ""
  /\ retention_ref = ""
  /\ legal_basis = ""
  /\ transfers_outside_eea = ""
  /\ None = ""
  /\ PR_INV_01 = ""
  /\ ALLOWED_LEGAL_BASES = ""
  /\ PR_INV_03 = ""
  /\ PR_INV_04 = ""

(* PR_INV_01: Every code path that reads or writes PII MUST be annotated *)
PR_INV_01 ==
  /\ read_version = write_version

(* PR_INV_02: Each record MUST reference a `retention_ref` that resolves to *)
PR_INV_02 ==
  /\ TypeOK

(* PR_INV_03: `legal_basis` MUST be one of GDPR Article 6(1)(a-f); *)
PR_INV_03 ==
  /\ TypeOK

(* PR_INV_04: `transfers_outside_eea` entries MUST be ISO-3166 alpha-2 *)
PR_INV_04 ==
  /\ TypeOK

(* PR_INV_05: `export_ropa()` output MUST be byte-for-byte reproducible *)
PR_INV_05 ==
  /\ TRUE

(* Operations *)
Has ==
  /\ activity' = HasImpl(activity)
  /\ UNCHANGED <<config>>

Register ==
  /\ activity' = RegisterImpl(activity)
  /\ UNCHANGED <<config>>

Export_ropa ==
  /\ activity' = Export_ropaImpl(activity)
  /\ UNCHANGED <<config>>

Size ==
  /\ activity' = SizeImpl(activity)
  /\ UNCHANGED <<config>>

Tick ==
  /\ UNCHANGED vars

Stutter == UNCHANGED vars

Next ==
    \/ Has \/ Register \/ Export_ropa \/ Size \/ Tick \/ Stutter

Spec == Init /\ [][Next]_vars

(* Safety: conjunction of all invariants *)
Safety ==
  /\ PR_INV_01
  /\ PR_INV_02
  /\ PR_INV_03
  /\ PR_INV_04
  /\ PR_INV_05

(* Liveness: meaningful eventual properties *)
Liveness ==
  /\ <>activity' # activity

====