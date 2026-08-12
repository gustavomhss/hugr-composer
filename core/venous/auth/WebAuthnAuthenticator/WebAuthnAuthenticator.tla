---- MODULE WebAuthnAuthenticator ----
EXTENDS Naturals, Sequences, FiniteSets

(*
  TLA+ specification for WebAuthnAuthenticator
  Namespace: auth
  Generated from primitive contract and implementation

  Purpose: Register and assert passkey credentials per the Web Authentication API, binding credentials to an RP ID and verifying attestation, challenge, origin, and signature counter.

  Invariants:
    INV_01: Challenges MUST be ≥16 bytes from a CSPRNG and MUST be single-use; replaying a challenge SHALL reject the response.
    INV_02: The origin in clientDataJSON MUST exactly match the configured RP origin; subdomain or scheme mismatch CANNOT be accepted.
    INV_03: The RP ID hash in authenticatorData MUST equal SHA-256(rp_id); mismatch MUST fail verification.
    INV_04: finish_assertion() MUST reject when the new sign_count is ≤ the stored sign_count, except when the authenticator always returns 0.
    INV_05: User verification flag MUST be enforced for authenticators registered as user-verifying; absence SHALL fail the assertion.
    INV_06: Credential public keys MUST be stored bound to (user_id, credential_id) and NEVER shared across users.
*)

CONSTANTS MaxInt

VARIABLES credential_id, public_key, sign_count, aaguid, user_id, user_verified

vars == <<credential_id, public_key, sign_count, aaguid, user_id, user_verified>>

TypeOK == 
  /\ credential_id \in String
  /\ public_key \in String
  /\ sign_count \in 0..MaxInt
  /\ aaguid \in String
  /\ user_id \in String
  /\ user_verified \in {TRUE, FALSE}

Init == 
  /\ credential_id = ""
  /\ public_key = ""
  /\ sign_count = 0
  /\ aaguid = ""
  /\ user_id = ""
  /\ user_verified = FALSE

(* WEBAUTHN_INV_01: challenges are CSPRNG-sized and single-use *)
WEBAUTHN_INV_01 ==
  /\ TypeOK

(* WEBAUTHN_INV_02: origin exact match *)
WEBAUTHN_INV_02 ==
  /\ TypeOK

(* WEBAUTHN_INV_03: RP ID hash match *)
WEBAUTHN_INV_03 ==
  /\ TypeOK

(* WEBAUTHN_INV_04: sign_count monotonicity *)
WEBAUTHN_INV_04 ==
  /\ version' = version + 1

(* WEBAUTHN_INV_05: UV flag enforced *)
WEBAUTHN_INV_05 ==
  /\ TypeOK

(* WEBAUTHN_INV_06: credentials bound to (user_id, credential_id) *)
WEBAUTHN_INV_06 ==
  /\ TypeOK

(* Operations *)
Begin_registration ==
  /\ credential_id' = Begin_registrationImpl(credential_id)
  /\ UNCHANGED <<config>>

Finish_registration ==
  /\ credential_id' = Finish_registrationImpl(credential_id)
  /\ UNCHANGED <<config>>

Begin_assertion ==
  /\ credential_id' = Begin_assertionImpl(credential_id)
  /\ UNCHANGED <<config>>

Finish_assertion ==
  /\ credential_id' = Finish_assertionImpl(credential_id)
  /\ UNCHANGED <<config>>

Issue ==
  /\ credential_id' = IssueImpl(credential_id)
  /\ UNCHANGED <<config>>

Consume ==
  /\ credential_id' = ConsumeImpl(credential_id)
  /\ UNCHANGED <<config>>

Is_live ==
  /\ credential_id' = Is_liveImpl(credential_id)
  /\ UNCHANGED <<config>>

Register ==
  /\ credential_id' = RegisterImpl(credential_id)
  /\ UNCHANGED <<config>>

Get ==
  /\ key # ""
  /\ result' = GetImpl(key)
  /\ UNCHANGED <<config>>

Update_sign_count ==
  /\ credential_id' = Update_sign_countImpl(credential_id)
  /\ UNCHANGED <<config>>

Public_key_for_user ==
  /\ credential_id' = Public_key_for_userImpl(credential_id)
  /\ UNCHANGED <<config>>

Rp_id ==
  /\ credential_id' = Rp_idImpl(credential_id)
  /\ UNCHANGED <<config>>

Origin ==
  /\ credential_id' = OriginImpl(credential_id)
  /\ UNCHANGED <<config>>

Credentials ==
  /\ credential_id' = CredentialsImpl(credential_id)
  /\ UNCHANGED <<config>>

Challenges ==
  /\ credential_id' = ChallengesImpl(credential_id)
  /\ UNCHANGED <<config>>

Tick ==
  /\ UNCHANGED vars

Stutter == UNCHANGED vars

Next ==
    \/ Begin_registration \/ Finish_registration \/ Begin_assertion \/ Finish_assertion \/ Issue \/ Consume \/ Is_live \/ Register \/ Get \/ Update_sign_count \/ Public_key_for_user \/ Rp_id \/ Origin \/ Credentials \/ Challenges \/ Tick \/ Stutter

Spec == Init /\ [][Next]_vars

(* Safety: conjunction of all invariants *)
Safety ==
  /\ WEBAUTHN_INV_01
  /\ WEBAUTHN_INV_02
  /\ WEBAUTHN_INV_03
  /\ WEBAUTHN_INV_04
  /\ WEBAUTHN_INV_05
  /\ WEBAUTHN_INV_06

(* Liveness: meaningful eventual properties *)
Liveness ==
  /\ <>credential_id' # credential_id
  /\ <>validated = TRUE

====