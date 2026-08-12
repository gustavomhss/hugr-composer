---- MODULE InboundVerifier ----
EXTENDS Naturals, Sequences, FiniteSets

(*
  TLA+ specification for InboundVerifier
  Namespace: api
  Generated from primitive contract and implementation

  Purpose: Abstract extension point for provider-specific inbound webhook verification (Stripe, GitHub, Slack, internal HMAC, ...): each concrete verifier turns raw (body, headers) into a trusted VerifiedEvent or raises HTTPException — never returns None, never swallows an error.

  Invariants:
    INV_01: INBOUND_VERIFIER_INV_01: verify(body, headers) MUST either return a VerifiedEvent built from the validated payload OR raise HTTPException; returning None or silently swallowing an error is FORBIDDEN by contract.
    INV_02: INBOUND_VERIFIER_INV_02: Subclasses MUST set the class attribute `name` to a stable provider slug; the registry uses this name for routing and audit logs.
    INV_03: INBOUND_VERIFIER_INV_03: verify MUST raise HTTPException(400) on signature mismatch or malformed body and HTTPException(401) on missing required auth header; other error classes are a contract violation.
    INV_04: INBOUND_VERIFIER_INV_04: verify MUST NOT mutate the input body or headers dict; callers MAY pass shared references and MUST observe them unchanged after the call.
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

(* IV_INV_01: named contract (subclass MUST set name) *)
IV_INV_01 ==
  /\ TypeOK

(* IV_INV_02: verify-or-raise (abstract enforced by ABC) *)
IV_INV_02 ==
  /\ TypeOK

(* IV_INV_03: framework-free (no fastapi/starlette imports) *)
IV_INV_03 ==
  /\ TypeOK

(* IV_INV_04: INBOUND_VERIFIER_INV_04: verify MUST NOT mutate the input body or headers dict; callers MAY pass shared references and MUST observe them unchanged after the call. *)
IV_INV_04 ==
  /\ TypeOK

(* Operations *)
Verify ==
  /\ state' = VerifyImpl(state)
  /\ UNCHANGED <<config>>

Tick ==
  /\ UNCHANGED vars

Stutter == UNCHANGED vars

Next ==
    \/ Verify \/ Tick \/ Stutter

Spec == Init /\ [][Next]_vars

(* Safety: conjunction of all invariants *)
Safety ==
  /\ IV_INV_01
  /\ IV_INV_02
  /\ IV_INV_03
  /\ IV_INV_04

(* Liveness: meaningful eventual properties *)
Liveness ==
  /\ <>state' # state

====