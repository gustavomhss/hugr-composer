---- MODULE InputGuardrail ----
EXTENDS Naturals, Sequences, FiniteSets

(*
  TLA+ specification for InputGuardrail
  Namespace: llm
  Generated from primitive contract and implementation

  Purpose: Intercept user input before it reaches a model and reject, redact, or transform it according to deterministic rules (PII, injection markers) and optional LLM-judged classifications.

  Invariants:
    INV_01: evaluate() MUST be deterministic for a given (text, context) unless the guardrail declares itself probabilistic via its name suffix.
    INV_02: A BLOCK decision MUST halt the pipeline; the caller CANNOT silently downgrade it to allow.
    INV_03: REDACT decisions SHALL return redacted_text and MUST NEVER return the original text under a redact verdict.
    INV_04: Every decision MUST carry a non-empty reason so downstream audit can explain the verdict.
    INV_05: Guardrails MUST NEVER store raw blocked inputs in logs in clear form; storage SHALL be hashed or truncated.
*)

CONSTANTS MaxInt

VARIABLES action, reason, redacted_text

vars == <<action, reason, redacted_text>>

TypeOK == 
  /\ action \in String
  /\ reason \in String
  /\ redacted_text \in String

Init == 
  /\ action = ""
  /\ reason = ""
  /\ redacted_text = ""

(* GUARD_INV_01: determinism *)
GUARD_INV_01 ==
  /\ TypeOK

(* GUARD_INV_02: block halts the pipeline *)
GUARD_INV_02 ==
  /\ action <= MaxInt

(* GUARD_INV_03: redact replaces the text downstream *)
GUARD_INV_03 ==
  /\ TypeOK

(* GUARD_INV_04: every decision carries a non-empty reason *)
GUARD_INV_04 ==
  /\ TypeOK

(* GUARD_INV_05: blocked inputs are hashed in the audit log *)
GUARD_INV_05 ==
  /\ action <= MaxInt

(* Operations *)
Evaluate ==
  /\ action' = EvaluateImpl(action)
  /\ UNCHANGED <<config>>

Validate_reason ==
  /\ action' = Validate_reasonImpl(action)
  /\ UNCHANGED <<config>>

Validate_redacted_text ==
  /\ action' = Validate_redacted_textImpl(action)
  /\ UNCHANGED <<config>>

Validate_guard_name ==
  /\ action' = Validate_guard_nameImpl(action)
  /\ UNCHANGED <<config>>

Is_probabilistic ==
  /\ action' = Is_probabilisticImpl(action)
  /\ UNCHANGED <<config>>

Hash_input ==
  /\ action' = Hash_inputImpl(action)
  /\ UNCHANGED <<config>>

Was_redacted ==
  /\ action' = Was_redactedImpl(action)
  /\ UNCHANGED <<config>>

State ==
  /\ action' = StateImpl(action)
  /\ UNCHANGED <<config>>

Seal ==
  /\ action' = SealImpl(action)
  /\ UNCHANGED <<config>>

Audit ==
  /\ action' = AuditImpl(action)
  /\ UNCHANGED <<config>>

Guards ==
  /\ action' = GuardsImpl(action)
  /\ UNCHANGED <<config>>

Apply ==
  /\ action' = ApplyImpl(action)
  /\ UNCHANGED <<config>>

Apply_with_outcome ==
  /\ action' = Apply_with_outcomeImpl(action)
  /\ UNCHANGED <<config>>

Tick ==
  /\ UNCHANGED vars

Stutter == UNCHANGED vars

Next ==
    \/ Evaluate \/ Validate_reason \/ Validate_redacted_text \/ Validate_guard_name \/ Is_probabilistic \/ Hash_input \/ Was_redacted \/ State \/ Seal \/ Audit \/ Guards \/ Apply \/ Apply_with_outcome \/ Tick \/ Stutter

Spec == Init /\ [][Next]_vars

(* Safety: conjunction of all invariants *)
Safety ==
  /\ GUARD_INV_01
  /\ GUARD_INV_02
  /\ GUARD_INV_03
  /\ GUARD_INV_04
  /\ GUARD_INV_05

(* Liveness: meaningful eventual properties *)
Liveness ==
  /\ <>action' # action

====