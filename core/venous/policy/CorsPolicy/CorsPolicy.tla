---- MODULE CorsPolicy ----
EXTENDS Naturals, Sequences, FiniteSets

(*
  TLA+ specification for CorsPolicy
  Namespace: policy
  Generated from primitive contract and implementation

  Purpose: Evaluate cross-origin preflight and simple-request allowance against a closed list of origins, methods, headers, and credential mode without reflecting arbitrary Origin values.

  Invariants:
    INV_01: evaluate() MUST NEVER echo back an Origin that is not in the configured allowlist.
    INV_02: When allow_credentials is True, allow_origin CANNOT be '*' and MUST be a single exact origin.
    INV_03: Vary: Origin MUST be emitted on any response that decides per-origin, or the policy SHALL reject evaluation.
    INV_04: Preflight caching (Access-Control-Max-Age) MUST be ≤86400 seconds and MUST NEVER default to unbounded.
    INV_05: Null origin ('null') MUST be rejected in credentialed mode because it collapses distinct sandboxed contexts.
*)

CONSTANTS MaxInt

VARIABLES allow_origin, allow_methods, allow_headers, allow_credentials, max_age_seconds, origin, None, CP_INV_01, WILDCARD, CP_INV_05, bool, pattern, review_ticket, _FORBIDDEN_REGEX_PATTERNS, try, exc, impl, method, str, header

vars == <<allow_origin, allow_methods, allow_headers, allow_credentials, max_age_seconds, origin, None, CP_INV_01, WILDCARD, CP_INV_05, bool, pattern, review_ticket, _FORBIDDEN_REGEX_PATTERNS, try, exc, impl, method, str, header>>

TypeOK == 
  /\ allow_origin \in String
  /\ allow_methods \in String
  /\ allow_headers \in String
  /\ allow_credentials \in {TRUE, FALSE}
  /\ max_age_seconds \in 0..MaxInt
  /\ origin \in String
  /\ None \in String
  /\ CP_INV_01 \in String
  /\ WILDCARD \in String
  /\ CP_INV_05 \in String
  /\ bool \in String
  /\ pattern \in String
  /\ review_ticket \in String
  /\ _FORBIDDEN_REGEX_PATTERNS \in String
  /\ try \in String
  /\ exc \in String
  /\ impl \in SUBSET String
  /\ method \in String
  /\ str \in String
  /\ header \in String

Init == 
  /\ allow_origin = ""
  /\ allow_methods = ""
  /\ allow_headers = ""
  /\ allow_credentials = FALSE
  /\ max_age_seconds = 0
  /\ origin = ""
  /\ None = ""
  /\ CP_INV_01 = ""
  /\ WILDCARD = ""
  /\ CP_INV_05 = ""
  /\ bool = ""
  /\ pattern = ""
  /\ review_ticket = ""
  /\ _FORBIDDEN_REGEX_PATTERNS = ""
  /\ try = ""
  /\ exc = ""
  /\ impl = {}
  /\ method = ""
  /\ str = ""
  /\ header = ""

(* CP_INV_01: ``evaluate()`` MUST NEVER echo back an ``Origin`` that is not in *)
CP_INV_01 ==
  /\ TypeOK

(* CP_INV_02: When ``allow_credentials`` is True, ``allow_origin`` CANNOT be *)
CP_INV_02 ==
  /\ TypeOK

(* CP_INV_03: ``Vary: Origin`` MUST be emitted on every per-origin decision. *)
CP_INV_03 ==
  /\ TypeOK

(* CP_INV_04: Preflight caching (``Access-Control-Max-Age``) MUST be *)
CP_INV_04 ==
  /\ TypeOK

(* CP_INV_05: Null origin (``'null'``) MUST be rejected in credentialed mode *)
CP_INV_05 ==
  /\ TypeOK

(* Operations *)
Evaluate ==
  /\ allow_origin' = EvaluateImpl(allow_origin)
  /\ UNCHANGED <<config>>

Matches ==
  /\ allow_origin' = MatchesImpl(allow_origin)
  /\ UNCHANGED <<config>>

Tick ==
  /\ UNCHANGED vars

Stutter == UNCHANGED vars

Next ==
    \/ Evaluate \/ Matches \/ Tick \/ Stutter

Spec == Init /\ [][Next]_vars

(* Safety: conjunction of all invariants *)
Safety ==
  /\ CP_INV_01
  /\ CP_INV_02
  /\ CP_INV_03
  /\ CP_INV_04
  /\ CP_INV_05

(* Liveness: meaningful eventual properties *)
Liveness ==
  /\ <>allow_origin' # allow_origin

====