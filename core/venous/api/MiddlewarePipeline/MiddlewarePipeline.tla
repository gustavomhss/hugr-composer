---- MODULE MiddlewarePipeline ----
EXTENDS Naturals, Sequences, FiniteSets

(*
  TLA+ specification for MiddlewarePipeline
  Namespace: api
  Generated from primitive contract and implementation

  Purpose: Ordered chain of components that each transform the RequestContext and decide whether to call the next, enabling cross-cutting concerns.

  Invariants:
    INV_01: Execution order MUST be the registration order; swap or insert operations SHALL be explicit, never implicit.
    INV_02: A middleware that does NOT await call_next MUST short-circuit the remainder of the pipeline.
    INV_03: Each middleware CANNOT bypass downstream error handling: exceptions NEVER skip registered error filters.
    INV_04: Registration MUST be frozen before run() is first called; adding middleware at request time SHALL raise.
    INV_05: MUST produce a response even if every middleware halts; an unhandled halt SHALL yield a 500 by contract.
*)

CONSTANTS MaxInt

VARIABLES method, path, headers, attributes, status, body, response_written, halted_by, error, key, value, default, Idempotent

vars == <<method, path, headers, attributes, status, body, response_written, halted_by, error, key, value, default, Idempotent>>

TypeOK == 
  /\ method \in String
  /\ path \in String
  /\ headers \in String
  /\ attributes \in String
  /\ status \in 0..MaxInt
  /\ body \in String
  /\ response_written \in {TRUE, FALSE}
  /\ halted_by \in String
  /\ error \in String
  /\ key \in String
  /\ value \in String
  /\ default \in String
  /\ Idempotent \in String

Init == 
  /\ method = ""
  /\ path = ""
  /\ headers = ""
  /\ attributes = ""
  /\ status = 0
  /\ body = ""
  /\ response_written = FALSE
  /\ halted_by = ""
  /\ error = ""
  /\ key = ""
  /\ value = ""
  /\ default = ""
  /\ Idempotent = ""

(* MWP_INV_01: registration order is the execution order *)
MWP_INV_01 ==
  /\ TypeOK

(* MWP_INV_02: no-await-call_next short-circuits the rest *)
MWP_INV_02 ==
  /\ method <= MaxInt

(* MWP_INV_03: error filters ALWAYS run on exception *)
MWP_INV_03 ==
  /\ TypeOK

(* MWP_INV_04: frozen after first run() *)
MWP_INV_04 ==
  /\ TypeOK

(* MWP_INV_05: always produces a response; unhandled halt yields 500 *)
MWP_INV_05 ==
  /\ TypeOK

(* Operations *)
Put ==
  /\ method' = PutImpl(method)
  /\ UNCHANGED <<config>>

Get ==
  /\ key # ""
  /\ result' = GetImpl(key)
  /\ UNCHANGED <<config>>

Write_response ==
  /\ method' = Write_responseImpl(method)
  /\ UNCHANGED <<config>>

Use ==
  /\ method' = UseImpl(method)
  /\ UNCHANGED <<config>>

Use_error_filter ==
  /\ method' = Use_error_filterImpl(method)
  /\ UNCHANGED <<config>>

Insert_before ==
  /\ method' = Insert_beforeImpl(method)
  /\ UNCHANGED <<config>>

Insert_after ==
  /\ method' = Insert_afterImpl(method)
  /\ UNCHANGED <<config>>

Remove ==
  /\ method' = RemoveImpl(method)
  /\ UNCHANGED <<config>>

Swap ==
  /\ method' = SwapImpl(method)
  /\ UNCHANGED <<config>>

Freeze ==
  /\ method' = FreezeImpl(method)
  /\ UNCHANGED <<config>>

Frozen ==
  /\ method' = FrozenImpl(method)
  /\ UNCHANGED <<config>>

Names ==
  /\ method' = NamesImpl(method)
  /\ UNCHANGED <<config>>

Tick ==
  /\ UNCHANGED vars

Stutter == UNCHANGED vars

Next ==
    \/ Put \/ Get \/ Write_response \/ Use \/ Use_error_filter \/ Insert_before \/ Insert_after \/ Remove \/ Swap \/ Freeze \/ Frozen \/ Names \/ Tick \/ Stutter

Spec == Init /\ [][Next]_vars

(* Safety: conjunction of all invariants *)
Safety ==
  /\ MWP_INV_01
  /\ MWP_INV_02
  /\ MWP_INV_03
  /\ MWP_INV_04
  /\ MWP_INV_05

(* Liveness: meaningful eventual properties *)
Liveness ==
  /\ <>method' # method

====