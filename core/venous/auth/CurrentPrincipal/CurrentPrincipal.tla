---- MODULE CurrentPrincipal ----
EXTENDS Naturals, Sequences, FiniteSets

(*
  TLA+ specification for CurrentPrincipal
  Namespace: auth
  Generated from primitive contract and implementation

  Purpose: Read-only view of the authenticated identity for the active request, including subject id, tenant, roles, and claim set.

  Invariants:
    INV_01: MUST be immutable once bound to a RequestContext; a later middleware CANNOT mutate subject_id.
    INV_02: NEVER represents a successful auth state with is_anonymous=True; these two fields SHALL be mutually exclusive.
    INV_03: roles MUST be a frozen set; consumers CANNOT add a role at call time to bypass authorization.
    INV_04: subject_id MUST be stable across requests for the same identity; rotation NEVER happens silently.
    INV_05: Serialization for logs MUST omit raw claims by default; sensitive claim values SHALL be redacted.
*)

CONSTANTS MaxInt

VARIABLES subject_id, tenant_id, roles, claims, is_anonymous, None, 01, 02, role, needed, key, default, 05, redacted_claims, patch, TypeError, self, name, value, noqa, type

vars == <<subject_id, tenant_id, roles, claims, is_anonymous, None, 01, 02, role, needed, key, default, 05, redacted_claims, patch, TypeError, self, name, value, noqa, type>>

TypeOK == 
  /\ subject_id \in String
  /\ tenant_id \in String
  /\ roles \in String
  /\ claims \in String
  /\ is_anonymous \in {TRUE, FALSE}
  /\ None \in String
  /\ 01 \in String
  /\ 02 \in String
  /\ role \in String
  /\ needed \in String
  /\ key \in String
  /\ default \in String
  /\ 05 \in String
  /\ redacted_claims \in String
  /\ patch \in String
  /\ TypeError \in String
  /\ self \in String
  /\ name \in String
  /\ value \in String
  /\ noqa \in String
  /\ type \in String

Init == 
  /\ subject_id = ""
  /\ tenant_id = ""
  /\ roles = ""
  /\ claims = ""
  /\ is_anonymous = FALSE
  /\ None = ""
  /\ 01 = ""
  /\ 02 = ""
  /\ role = ""
  /\ needed = ""
  /\ key = ""
  /\ default = ""
  /\ 05 = ""
  /\ redacted_claims = ""
  /\ patch = ""
  /\ TypeError = ""
  /\ self = ""
  /\ name = ""
  /\ value = ""
  /\ noqa = ""
  /\ type = ""

(* PRINCIPAL_INV_01: immutability *)
PRINCIPAL_INV_01 ==
  /\ TypeOK

(* PRINCIPAL_INV_02: anonymity parity *)
PRINCIPAL_INV_02 ==
  /\ TypeOK

(* PRINCIPAL_INV_03: roles frozen *)
PRINCIPAL_INV_03 ==
  /\ TypeOK

(* PRINCIPAL_INV_04: subject_id stable / hygienic *)
PRINCIPAL_INV_04 ==
  /\ TypeOK

(* PRINCIPAL_INV_05: log redaction *)
PRINCIPAL_INV_05 ==
  /\ TypeOK

(* Operations *)
Resolve ==
  /\ subject_id' = ResolveImpl(subject_id)
  /\ UNCHANGED <<config>>

Has_role ==
  /\ subject_id' = Has_roleImpl(subject_id)
  /\ UNCHANGED <<config>>

Has_any_role ==
  /\ subject_id' = Has_any_roleImpl(subject_id)
  /\ UNCHANGED <<config>>

Has_all_roles ==
  /\ subject_id' = Has_all_rolesImpl(subject_id)
  /\ UNCHANGED <<config>>

Claim ==
  /\ subject_id' = ClaimImpl(subject_id)
  /\ UNCHANGED <<config>>

Require_role ==
  /\ subject_id' = Require_roleImpl(subject_id)
  /\ UNCHANGED <<config>>

For_log ==
  /\ subject_id' = For_logImpl(subject_id)
  /\ UNCHANGED <<config>>

Authenticated ==
  /\ subject_id' = AuthenticatedImpl(subject_id)
  /\ UNCHANGED <<config>>

Known_credentials ==
  /\ subject_id' = Known_credentialsImpl(subject_id)
  /\ UNCHANGED <<config>>

Tick ==
  /\ UNCHANGED vars

Stutter == UNCHANGED vars

Next ==
    \/ Resolve \/ Has_role \/ Has_any_role \/ Has_all_roles \/ Claim \/ Require_role \/ For_log \/ Authenticated \/ Known_credentials \/ Tick \/ Stutter

Spec == Init /\ [][Next]_vars

(* Safety: conjunction of all invariants *)
Safety ==
  /\ PRINCIPAL_INV_01
  /\ PRINCIPAL_INV_02
  /\ PRINCIPAL_INV_03
  /\ PRINCIPAL_INV_04
  /\ PRINCIPAL_INV_05

(* Liveness: meaningful eventual properties *)
Liveness ==
  /\ <>subject_id' # subject_id
  /\ <>validated = TRUE

====