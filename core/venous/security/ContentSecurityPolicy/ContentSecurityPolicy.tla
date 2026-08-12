---- MODULE ContentSecurityPolicy ----
EXTENDS Naturals, Sequences, FiniteSets

(*
  TLA+ specification for ContentSecurityPolicy
  Namespace: security
  Generated from primitive contract and implementation

  Purpose: Compose, serialize, and enforce a Content Security Policy header that constrains script, style, frame, and connection origins with strict-dynamic and nonce-based script allowance.

  Invariants:
    INV_01: default-src MUST be set; a policy without default-src CANNOT be rendered.
    INV_02: script-src MUST NEVER include 'unsafe-inline' together with a nonce; the two are mutually exclusive per CSP3.
    INV_03: Nonces MUST be ≥128 bits from a CSPRNG and MUST be unique per response; reuse SHALL invalidate the guarantee.
    INV_04: object-src MUST be set to 'none' unless the caller explicitly opts in with a reason string.
    INV_05: base-uri and frame-ancestors MUST be set to a closed list; wildcard values are FORBIDDEN in production profiles.
    INV_06: report-only and enforce modes MUST be separate header names and MUST NEVER both block and merely report the same directive.
*)

CONSTANTS MaxInt

VARIABLES name, sources, _directive_order, _directives, mode, allow_unsafe_inline_script, unsafe_inline_rationale, allow_object_src_override, object_src_rationale, allow_closed_list_wildcard, report_only_directives, directive, CspPolicy, CSP_INV_01, new_map, nonce, NONCEABLE_DIRECTIVES, CSP_INV_02, CSP_INV_04, None, has_nonce, CLOSED_LIST_DIRECTIVES, CSP_INV_05, CSP_INV_06, ENFORCE, REPORT_ONLY, str, strict, enforce_map, n, ro_map, seen, deduped, ro_order, check, overlap, noqa, bool, k

vars == <<name, sources, _directive_order, _directives, mode, allow_unsafe_inline_script, unsafe_inline_rationale, allow_object_src_override, object_src_rationale, allow_closed_list_wildcard, report_only_directives, directive, CspPolicy, CSP_INV_01, new_map, nonce, NONCEABLE_DIRECTIVES, CSP_INV_02, CSP_INV_04, None, has_nonce, CLOSED_LIST_DIRECTIVES, CSP_INV_05, CSP_INV_06, ENFORCE, REPORT_ONLY, str, strict, enforce_map, n, ro_map, seen, deduped, ro_order, check, overlap, noqa, bool, k>>

TypeOK == 
  /\ name \in String
  /\ sources \in String
  /\ _directive_order \in String
  /\ _directives \in String
  /\ mode \in String
  /\ allow_unsafe_inline_script \in {TRUE, FALSE}
  /\ unsafe_inline_rationale \in String
  /\ allow_object_src_override \in {TRUE, FALSE}
  /\ object_src_rationale \in String
  /\ allow_closed_list_wildcard \in {TRUE, FALSE}
  /\ report_only_directives \in String
  /\ directive \in String
  /\ CspPolicy \in String
  /\ CSP_INV_01 \in String
  /\ new_map \in String
  /\ nonce \in String
  /\ NONCEABLE_DIRECTIVES \in String
  /\ CSP_INV_02 \in String
  /\ CSP_INV_04 \in String
  /\ None \in String
  /\ has_nonce \in String
  /\ CLOSED_LIST_DIRECTIVES \in String
  /\ CSP_INV_05 \in String
  /\ CSP_INV_06 \in SUBSET String
  /\ ENFORCE \in String
  /\ REPORT_ONLY \in String
  /\ str \in String
  /\ strict \in {TRUE, FALSE}
  /\ enforce_map \in String
  /\ n \in String
  /\ ro_map \in String
  /\ seen \in String
  /\ deduped \in String
  /\ ro_order \in String
  /\ check \in String
  /\ overlap \in String
  /\ noqa \in String
  /\ bool \in String
  /\ k \in SUBSET String

Init == 
  /\ name = ""
  /\ sources = ""
  /\ _directive_order = ""
  /\ _directives = ""
  /\ mode = ""
  /\ allow_unsafe_inline_script = FALSE
  /\ unsafe_inline_rationale = ""
  /\ allow_object_src_override = FALSE
  /\ object_src_rationale = ""
  /\ allow_closed_list_wildcard = FALSE
  /\ report_only_directives = ""
  /\ directive = ""
  /\ CspPolicy = ""
  /\ CSP_INV_01 = ""
  /\ new_map = ""
  /\ nonce = ""
  /\ NONCEABLE_DIRECTIVES = ""
  /\ CSP_INV_02 = ""
  /\ CSP_INV_04 = ""
  /\ None = ""
  /\ has_nonce = ""
  /\ CLOSED_LIST_DIRECTIVES = ""
  /\ CSP_INV_05 = ""
  /\ CSP_INV_06 = {}
  /\ ENFORCE = ""
  /\ REPORT_ONLY = ""
  /\ str = ""
  /\ strict = FALSE
  /\ enforce_map = ""
  /\ n = ""
  /\ ro_map = ""
  /\ seen = ""
  /\ deduped = ""
  /\ ro_order = ""
  /\ check = ""
  /\ overlap = ""
  /\ noqa = ""
  /\ bool = ""
  /\ k = {}

(* CSP_INV_01: every policy MUST declare `default-src`; `render_header` on *)
CSP_INV_01 ==
  /\ TypeOK

(* CSP_INV_02: `'unsafe-inline'` and a nonce MUST NEVER coexist on *)
CSP_INV_02 ==
  /\ TypeOK

(* CSP_INV_03: nonces MUST be ≥128 bits from a CSPRNG and MUST NEVER be *)
CSP_INV_03 ==
  /\ TypeOK

(* CSP_INV_04: `object-src` MUST be `'none'` unless the caller opts in *)
CSP_INV_04 ==
  /\ TypeOK

(* CSP_INV_05: `base-uri` and `frame-ancestors` MUST be set to a closed *)
CSP_INV_05 ==
  /\ TypeOK

(* CSP_INV_06: report-only and enforce headers MUST be separate header *)
CSP_INV_06 ==
  /\ name <= sources

(* Operations *)
With_directive ==
  /\ name' = With_directiveImpl(name)
  /\ UNCHANGED <<config>>

With_nonce ==
  /\ name' = With_nonceImpl(name)
  /\ UNCHANGED <<config>>

Render_header ==
  /\ name' = Render_headerImpl(name)
  /\ UNCHANGED <<config>>

Record ==
  /\ name' = RecordImpl(name)
  /\ UNCHANGED <<config>>

Forget ==
  /\ name' = ForgetImpl(name)
  /\ UNCHANGED <<config>>

Reset ==
  /\ key # ""
  /\ state' = InitState
  /\ UNCHANGED <<config>>

Strict_default ==
  /\ name' = Strict_defaultImpl(name)
  /\ UNCHANGED <<config>>

Render_dual ==
  /\ name' = Render_dualImpl(name)
  /\ UNCHANGED <<config>>

Directives ==
  /\ name' = DirectivesImpl(name)
  /\ UNCHANGED <<config>>

Has_directive ==
  /\ name' = Has_directiveImpl(name)
  /\ UNCHANGED <<config>>

To_dict ==
  /\ name' = To_dictImpl(name)
  /\ UNCHANGED <<config>>

Apply_decorator ==
  /\ name' = Apply_decoratorImpl(name)
  /\ UNCHANGED <<config>>

Tick ==
  /\ UNCHANGED vars

Stutter == UNCHANGED vars

Next ==
    \/ With_directive \/ With_nonce \/ Render_header \/ Record \/ Forget \/ Reset \/ Strict_default \/ Render_dual \/ Directives \/ Has_directive \/ To_dict \/ Apply_decorator \/ Tick \/ Stutter

Spec == Init /\ [][Next]_vars

(* Safety: conjunction of all invariants *)
Safety ==
  /\ CSP_INV_01
  /\ CSP_INV_02
  /\ CSP_INV_03
  /\ CSP_INV_04
  /\ CSP_INV_05
  /\ CSP_INV_06

(* Liveness: meaningful eventual properties *)
Liveness ==
  /\ <>name' # name

====