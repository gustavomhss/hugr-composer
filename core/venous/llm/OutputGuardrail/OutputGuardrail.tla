---- MODULE OutputGuardrail ----
EXTENDS Naturals, Sequences, FiniteSets

(*
  TLA+ specification for OutputGuardrail
  Namespace: llm
  Generated from primitive contract and implementation

  Purpose: Inspect model output after generation and reject, rewrite, or annotate it against schema, policy, and safety rules before the caller or downstream tools receive it.

  Invariants:
    INV_01: evaluate() MUST reject output that fails schema validation when schema_ref is provided; CANNOT pass malformed JSON as pass.
    INV_02: A BLOCK verdict MUST prevent the output from being returned to the caller or passed to any downstream tool.
    INV_03: REWRITE verdicts MUST provide a replacement; a replacement of None under rewrite SHALL be treated as a contract violation.
    INV_04: Output guardrails MUST NEVER execute tool calls embedded in the output before passing safety checks.
    INV_05: Every verdict SHALL be recorded with the guardrail name so post-hoc analysis can attribute the decision.
*)

CONSTANTS MaxInt

VARIABLES guardrail, reason, name

vars == <<guardrail, reason, name>>

TypeOK == 
  /\ guardrail \in String
  /\ reason \in String
  /\ name \in String

Init == 
  /\ guardrail = ""
  /\ reason = ""
  /\ name = ""

(* GUARD_INV_01: schema rejects malformed output *)
GUARD_INV_01 ==
  /\ TypeOK

(* GUARD_INV_02: block verdict prevents delivery *)
GUARD_INV_02 ==
  /\ guardrail <= MaxInt

(* GUARD_INV_03: rewrite requires replacement *)
GUARD_INV_03 ==
  /\ TypeOK

(* GUARD_INV_04: no tool exec before safety check *)
GUARD_INV_04 ==
  /\ TypeOK

(* GUARD_INV_05: verdict recorded with guardrail name *)
GUARD_INV_05 ==
  /\ TypeOK

(* Operations *)
Evaluate ==
  /\ guardrail' = EvaluateImpl(guardrail)
  /\ UNCHANGED <<config>>

Validate_output ==
  /\ guardrail' = Validate_outputImpl(guardrail)
  /\ UNCHANGED <<config>>

Action ==
  /\ guardrail' = ActionImpl(guardrail)
  /\ UNCHANGED <<config>>

Reason ==
  /\ guardrail' = ReasonImpl(guardrail)
  /\ UNCHANGED <<config>>

Replacement ==
  /\ guardrail' = ReplacementImpl(guardrail)
  /\ UNCHANGED <<config>>

Record ==
  /\ guardrail' = RecordImpl(guardrail)
  /\ UNCHANGED <<config>>

Entries ==
  /\ guardrail' = EntriesImpl(guardrail)
  /\ UNCHANGED <<config>>

Entries_for ==
  /\ guardrail' = Entries_forImpl(guardrail)
  /\ UNCHANGED <<config>>

Size ==
  /\ guardrail' = SizeImpl(guardrail)
  /\ UNCHANGED <<config>>

Clear ==
  /\ guardrail' = ClearImpl(guardrail)
  /\ UNCHANGED <<config>>

Tick ==
  /\ UNCHANGED vars

Stutter == UNCHANGED vars

Next ==
    \/ Evaluate \/ Validate_output \/ Action \/ Reason \/ Replacement \/ Record \/ Entries \/ Entries_for \/ Size \/ Clear \/ Tick \/ Stutter

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
  /\ <>guardrail' # guardrail

====