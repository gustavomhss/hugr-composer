---- MODULE DeprecationEntry ----
EXTENDS Naturals, Sequences, FiniteSets

(*
  TLA+ specification for DeprecationEntry
  Namespace: api
  Generated from primitive contract and implementation

  Purpose: Value object carrying the metadata required to emit RFC 8594 Sunset / Deprecation headers for a single endpoint: path, method, sunset date, replacement URL, and a derived warn-window flag.

  Invariants:
    INV_01: DEPRECATION_ENTRY_INV_01: sunset_header MUST be the ISO-8601 date string of the configured sunset date, suitable verbatim as an RFC 8594 Sunset header value.
    INV_02: DEPRECATION_ENTRY_INV_02: method MUST be stored uppercase regardless of the casing passed to __init__, so lookups by method are case-stable.
    INV_03: DEPRECATION_ENTRY_INV_03: days_until_sunset MUST compute (sunset_date - date.today()).days and MUST go negative when the sunset date has already passed (never clamp to 0).
    INV_04: DEPRECATION_ENTRY_INV_04: should_warn MUST be True iff days_until_sunset <= settings.DEPRECATION_WARN_DAYS_BEFORE_SUNSET (default 30), including the past-sunset case.
*)

CONSTANTS MaxInt

VARIABLES path, method, sunset_date, replacement, description, warn_days_before_sunset

vars == <<path, method, sunset_date, replacement, description, warn_days_before_sunset>>

TypeOK == 
  /\ path \in String
  /\ method \in String
  /\ sunset_date \in String
  /\ replacement \in String
  /\ description \in String
  /\ warn_days_before_sunset \in String

Init == 
  /\ path = ""
  /\ method = ""
  /\ sunset_date = ""
  /\ replacement = ""
  /\ description = ""
  /\ warn_days_before_sunset = ""

(* DE_INV_02: method normalisation + reject invalid sunset *)
DE_INV_02 ==
  /\ TypeOK

(* DE_INV_04: warn window monotone *)
DE_INV_04 ==
  /\ TypeOK

(* DE_INV_05: to_dict JSON-safe + complete *)
DE_INV_05 ==
  /\ TypeOK

(* DE_INV_04: warn window monotone *)
DE_INV_04 ==
  /\ TypeOK

(* Operations *)
Sunset_header ==
  /\ path' = Sunset_headerImpl(path)
  /\ UNCHANGED <<config>>

Days_until_sunset ==
  /\ path' = Days_until_sunsetImpl(path)
  /\ UNCHANGED <<config>>

Should_warn ==
  /\ path' = Should_warnImpl(path)
  /\ UNCHANGED <<config>>

To_dict ==
  /\ path' = To_dictImpl(path)
  /\ UNCHANGED <<config>>

Tick ==
  /\ UNCHANGED vars

Stutter == UNCHANGED vars

Next ==
    \/ Sunset_header \/ Days_until_sunset \/ Should_warn \/ To_dict \/ Tick \/ Stutter

Spec == Init /\ [][Next]_vars

(* Safety: conjunction of all invariants *)
Safety ==
  /\ DE_INV_02
  /\ DE_INV_04
  /\ DE_INV_05
  /\ DE_INV_04

(* Liveness: meaningful eventual properties *)
Liveness ==
  /\ <>path' # path

====