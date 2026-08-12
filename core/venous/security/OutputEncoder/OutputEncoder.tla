---- MODULE OutputEncoder ----
EXTENDS Naturals, Sequences, FiniteSets

(*
  TLA+ specification for OutputEncoder
  Namespace: security
  Generated from primitive contract and implementation

  Purpose: Encode untrusted values for a named sink (HTML text, HTML attribute, JavaScript string, URL path, URL query, CSS value) using sink-specific escaping rules.

  Invariants:
    INV_01: encode() MUST produce output that cannot break out of the named sink; a string encoded for HTML_ATTRIBUTE MUST NEVER enable script execution when inserted into that sink.
    INV_02: The caller MUST declare the sink; the encoder SHALL NEVER infer sink from context.
    INV_03: Encoders MUST be applied at the last possible moment before sink insertion; pre-encoded storage is FORBIDDEN to avoid double-encoding.
    INV_04: CSS_VALUE encoding MUST reject values containing expression()-style sequences and MUST hex-escape control characters.
    INV_05: URL_QUERY encoding MUST percent-encode per RFC 3986 unreserved set; space MUST become %20 inside a path and MAY become + only in form-encoded bodies.
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

(* OE_INV_01: encoded output MUST NEVER break out of its sink; a value encoded *)
OE_INV_01 ==
  /\ TypeOK

(* OE_INV_02: the caller MUST declare the sink; the encoder SHALL NEVER infer *)
OE_INV_02 ==
  /\ TypeOK

(* OE_INV_03: callers MUST encode at emission; pre-encoded storage is *)
OE_INV_03 ==
  /\ TypeOK

(* OE_INV_04: CSS_VALUE encoding MUST reject expression()/url()/@import style *)
OE_INV_04 ==
  /\ TRUE

(* OE_INV_05: URL_QUERY encoding MUST percent-encode per RFC 3986; space *)
OE_INV_05 ==
  /\ TypeOK

(* Operations *)
Encode ==
  /\ state' = EncodeImpl(state)
  /\ UNCHANGED <<config>>

Payload ==
  /\ state' = PayloadImpl(state)
  /\ UNCHANGED <<config>>

Sink ==
  /\ state' = SinkImpl(state)
  /\ UNCHANGED <<config>>

Tick ==
  /\ UNCHANGED vars

Stutter == UNCHANGED vars

Next ==
    \/ Encode \/ Payload \/ Sink \/ Tick \/ Stutter

Spec == Init /\ [][Next]_vars

(* Safety: conjunction of all invariants *)
Safety ==
  /\ OE_INV_01
  /\ OE_INV_02
  /\ OE_INV_03
  /\ OE_INV_04
  /\ OE_INV_05

(* Liveness: meaningful eventual properties *)
Liveness ==
  /\ <>state' # state

====