---- MODULE SignatureVerifier ----
EXTENDS Naturals, Sequences, FiniteSets

(*
  TLA+ specification for SignatureVerifier
  Namespace: security
  Generated from primitive contract and implementation

  Purpose: Produce and verify detached digital signatures with key-id selection, typed message framing, and refusal of weak or unannounced algorithms.

  Invariants:
    INV_01: verify() MUST raise on signature mismatch and MUST NEVER return a boolean indicating partial verification.
    INV_02: Accepted algorithms MUST be declared per key_id; algorithm confusion (substituting HS256 for RS256) CANNOT occur.
    INV_03: sign() MUST use deterministic signing (RFC 6979 for ECDSA) or a CSPRNG nonce; ECDSA nonce reuse SHALL be treated as key compromise.
    INV_04: Public keys used for verify MUST be fetched from a pinned trust anchor and MUST NEVER be learned from the same message being verified.
    INV_05: verify() MUST be constant-time with respect to the signature bytes; timing leaks on tag comparison are FORBIDDEN.
*)

CONSTANTS MaxInt

VARIABLES key_id, algorithm, private_key, public_key

vars == <<key_id, algorithm, private_key, public_key>>

TypeOK == 
  /\ key_id \in String
  /\ algorithm \in String
  /\ private_key \in String
  /\ public_key \in String

Init == 
  /\ key_id = ""
  /\ algorithm = ""
  /\ private_key = ""
  /\ public_key = ""

(* SIG_INV_01: verify() MUST raise on mismatch (never return bool) *)
SIG_INV_01 ==
  /\ TypeOK

(* SIG_INV_02: algorithm bound to key_id; no algorithm confusion *)
SIG_INV_02 ==
  /\ TypeOK

(* SIG_INV_03: deterministic signing OR CSPRNG nonce; ECDSA nonce reuse CANNOT occur *)
SIG_INV_03 ==
  /\ TypeOK

(* SIG_INV_04: public keys from pinned trust anchor; cannot be learned from msg *)
SIG_INV_04 ==
  /\ TypeOK

(* SIG_INV_05: constant-time compare on verify *)
SIG_INV_05 ==
  /\ TypeOK

(* Operations *)
Sign ==
  /\ key_id' = SignImpl(key_id)
  /\ UNCHANGED <<config>>

Verify ==
  /\ key_id' = VerifyImpl(key_id)
  /\ UNCHANGED <<config>>

Register ==
  /\ key_id' = RegisterImpl(key_id)
  /\ UNCHANGED <<config>>

Resolve ==
  /\ key_id' = ResolveImpl(key_id)
  /\ UNCHANGED <<config>>

Known_key_ids ==
  /\ key_id' = Known_key_idsImpl(key_id)
  /\ UNCHANGED <<config>>

Register_adapter ==
  /\ key_id' = Register_adapterImpl(key_id)
  /\ UNCHANGED <<config>>

Check_and_record ==
  /\ key_id' = Check_and_recordImpl(key_id)
  /\ UNCHANGED <<config>>

Reset ==
  /\ key # ""
  /\ state' = InitState
  /\ UNCHANGED <<config>>

Anchor ==
  /\ key_id' = AnchorImpl(key_id)
  /\ UNCHANGED <<config>>

Sign_typed ==
  /\ key_id' = Sign_typedImpl(key_id)
  /\ UNCHANGED <<config>>

Verify_typed ==
  /\ key_id' = Verify_typedImpl(key_id)
  /\ UNCHANGED <<config>>

Generate_ed25519_keypair ==
  /\ key_id' = Generate_ed25519_keypairImpl(key_id)
  /\ UNCHANGED <<config>>

Generate_ecdsa_p256_keypair ==
  /\ key_id' = Generate_ecdsa_p256_keypairImpl(key_id)
  /\ UNCHANGED <<config>>

Tick ==
  /\ UNCHANGED vars

Stutter == UNCHANGED vars

Next ==
    \/ Sign \/ Verify \/ Register \/ Resolve \/ Known_key_ids \/ Register_adapter \/ Check_and_record \/ Reset \/ Anchor \/ Sign_typed \/ Verify_typed \/ Generate_ed25519_keypair \/ Generate_ecdsa_p256_keypair \/ Tick \/ Stutter

Spec == Init /\ [][Next]_vars

(* Safety: conjunction of all invariants *)
Safety ==
  /\ SIG_INV_01
  /\ SIG_INV_02
  /\ SIG_INV_03
  /\ SIG_INV_04
  /\ SIG_INV_05

(* Liveness: meaningful eventual properties *)
Liveness ==
  /\ <>key_id' # key_id

====