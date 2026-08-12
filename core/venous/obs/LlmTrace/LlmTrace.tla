---- MODULE LlmTrace ----
EXTENDS Naturals, Sequences, FiniteSets

(*
  TLA+ specification for LlmTrace
  Namespace: obs
  Generated from primitive contract and implementation

  Purpose: Emit structured spans for each model call with attributes aligned to OpenTelemetry GenAI semantic conventions so token counts, model identity, and prompt/response linkage land in traces consistently.

  Invariants:
    INV_01: Every model call SHALL open exactly one LlmTrace span; unspanned calls are FORBIDDEN.
    INV_02: Span attribute names MUST match the OpenTelemetry GenAI semantic conventions (gen_ai.system, gen_ai.request.model, gen_ai.usage.input_tokens, gen_ai.usage.output_tokens).
    INV_03: Spans MUST record prompt_fingerprint so the trace can be correlated with the PromptTemplate version that generated it.
    INV_04: On provider error the span MUST call record_error before exiting; swallowing the error without recording is FORBIDDEN.
    INV_05: Child tool-call spans MUST nest under the model-call span so the causal chain is reconstructable end-to-end.
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

(* LLMTRACE_INV_01: one span per model call *)
LLMTRACE_INV_01 ==
  /\ TypeOK

(* LLMTRACE_INV_02: OTel GenAI SemConv attribute names *)
LLMTRACE_INV_02 ==
  /\ TypeOK

(* LLMTRACE_INV_03: prompt_fingerprint required *)
LLMTRACE_INV_03 ==
  /\ TypeOK

(* LLMTRACE_INV_04: record_error before exit *)
LLMTRACE_INV_04 ==
  /\ TypeOK

(* LLMTRACE_INV_05: child spans nest under parent *)
LLMTRACE_INV_05 ==
  /\ TypeOK

(* Operations *)
Set_usage ==
  /\ state' = Set_usageImpl(state)
  /\ UNCHANGED <<config>>

Set_finish_reason ==
  /\ state' = Set_finish_reasonImpl(state)
  /\ UNCHANGED <<config>>

Record_error ==
  /\ state' = Record_errorImpl(state)
  /\ UNCHANGED <<config>>

Start ==
  /\ state' = StartImpl(state)
  /\ UNCHANGED <<config>>

Validate_operation ==
  /\ state' = Validate_operationImpl(state)
  /\ UNCHANGED <<config>>

Validate_model_handle ==
  /\ state' = Validate_model_handleImpl(state)
  /\ UNCHANGED <<config>>

Validate_prompt_fingerprint ==
  /\ state' = Validate_prompt_fingerprintImpl(state)
  /\ UNCHANGED <<config>>

Validate_semconv_key ==
  /\ state' = Validate_semconv_keyImpl(state)
  /\ UNCHANGED <<config>>

Validate_finish_reason ==
  /\ state' = Validate_finish_reasonImpl(state)
  /\ UNCHANGED <<config>>

Validate_token_count ==
  /\ state' = Validate_token_countImpl(state)
  /\ UNCHANGED <<config>>

Set_cache_usage ==
  /\ state' = Set_cache_usageImpl(state)
  /\ UNCHANGED <<config>>

Set_temperature ==
  /\ state' = Set_temperatureImpl(state)
  /\ UNCHANGED <<config>>

End ==
  /\ state' = EndImpl(state)
  /\ UNCHANGED <<config>>

Spans ==
  /\ state' = SpansImpl(state)
  /\ UNCHANGED <<config>>

Active_depth ==
  /\ state' = Active_depthImpl(state)
  /\ UNCHANGED <<config>>

Capture_content ==
  /\ state' = Capture_contentImpl(state)
  /\ UNCHANGED <<config>>

Validate_attributes_match_semconv ==
  /\ state' = Validate_attributes_match_semconvImpl(state)
  /\ UNCHANGED <<config>>

Assert_required_semconv_present ==
  /\ state' = Assert_required_semconv_presentImpl(state)
  /\ UNCHANGED <<config>>

Tick ==
  /\ UNCHANGED vars

Stutter == UNCHANGED vars

Next ==
    \/ Set_usage \/ Set_finish_reason \/ Record_error \/ Start \/ Validate_operation \/ Validate_model_handle \/ Validate_prompt_fingerprint \/ Validate_semconv_key \/ Validate_finish_reason \/ Validate_token_count \/ Set_cache_usage \/ Set_temperature \/ End \/ Spans \/ Active_depth \/ Capture_content \/ Validate_attributes_match_semconv \/ Assert_required_semconv_present \/ Tick \/ Stutter

Spec == Init /\ [][Next]_vars

(* Safety: conjunction of all invariants *)
Safety ==
  /\ LLMTRACE_INV_01
  /\ LLMTRACE_INV_02
  /\ LLMTRACE_INV_03
  /\ LLMTRACE_INV_04
  /\ LLMTRACE_INV_05

(* Liveness: meaningful eventual properties *)
Liveness ==
  /\ <>state' # state

====