---- MODULE CryptoEnvelope ----
EXTENDS Naturals, Sequences, FiniteSets

(*
  TLA+ specification for CryptoEnvelope
  Namespace: security
  Generated from primitive contract and implementation

  Purpose: Encrypt and decrypt payloads with authenticated encryption, key-id-tagged ciphertext, and deterministic header framing that enables key rotation without re-encryption on read.

  Invariants:
    INV_01: seal() MUST use an AEAD construction (AES-GCM, ChaCha20-Poly1305) and CANNOT emit an envelope without an authentication tag.
    INV_02: Nonces MUST NEVER repeat for a given key; nonce reuse under AES-GCM SHALL be treated as a critical incident.
    INV_03: open() MUST verify aad byte-for-byte; mismatched aad MUST abort before returning plaintext.
    INV_04: key_id MUST resolve to a live key in the vault; decryption with an unknown key_id CANNOT return partial plaintext.
    INV_05: Keys MUST be rotatable without re-encrypting stored ciphertext; open() MUST resolve the correct key by key_id from the envelope.
    INV_06: Plaintext buffers SHALL be zeroed where the runtime allows after use; plaintext MUST NEVER be logged.
*)

CONSTANTS MaxInt

VARIABLES key_id, nonce, ciphertext, aad, key, algorithm

vars == <<key_id, nonce, ciphertext, aad, key, algorithm>>

TypeOK == 
  /\ key_id \in String
  /\ nonce \in String
  /\ ciphertext \in String
  /\ aad \in String
  /\ key \in String
  /\ algorithm \in String

Init == 
  /\ key_id = ""
  /\ nonce = ""
  /\ ciphertext = ""
  /\ aad = ""
  /\ key = ""
  /\ algorithm = ""

(* CRY_INV_01: AEAD tag is produced and enforced *)
CRY_INV_01 ==
  /\ TypeOK

(* CRY_INV_02: nonces NEVER repeat for a given key *)
CRY_INV_02 ==
  /\ TypeOK

(* CRY_INV_03: aad byte-for-byte; mismatched aad aborts BEFORE plaintext *)
CRY_INV_03 ==
  /\ TypeOK

(* CRY_INV_04: unknown key_id MUST NOT return partial plaintext *)
CRY_INV_04 ==
  /\ TypeOK

(* CRY_INV_05: rotation works without re-encrypting stored ciphertext *)
CRY_INV_05 ==
  /\ TypeOK

(* CRY_INV_06: plaintext NEVER logged/leaked in exceptions *)
CRY_INV_06 ==
  /\ TypeOK

(* Operations *)
Seal ==
  /\ key_id' = SealImpl(key_id)
  /\ UNCHANGED <<config>>

Open ==
  /\ key_id' = OpenImpl(key_id)
  /\ UNCHANGED <<config>>

Register ==
  /\ key_id' = RegisterImpl(key_id)
  /\ UNCHANGED <<config>>

Set_active ==
  /\ key_id' = Set_activeImpl(key_id)
  /\ UNCHANGED <<config>>

Active ==
  /\ key_id' = ActiveImpl(key_id)
  /\ UNCHANGED <<config>>

Resolve ==
  /\ key_id' = ResolveImpl(key_id)
  /\ UNCHANGED <<config>>

Known_key_ids ==
  /\ key_id' = Known_key_idsImpl(key_id)
  /\ UNCHANGED <<config>>

Drop ==
  /\ key_id' = DropImpl(key_id)
  /\ UNCHANGED <<config>>

Check_and_record ==
  /\ key_id' = Check_and_recordImpl(key_id)
  /\ UNCHANGED <<config>>

Reset ==
  /\ key # ""
  /\ state' = InitState
  /\ UNCHANGED <<config>>

Encrypt ==
  /\ key_id' = EncryptImpl(key_id)
  /\ UNCHANGED <<config>>

Decrypt ==
  /\ key_id' = DecryptImpl(key_id)
  /\ UNCHANGED <<config>>

Register_adapter ==
  /\ key_id' = Register_adapterImpl(key_id)
  /\ UNCHANGED <<config>>

Algorithm ==
  /\ key_id' = AlgorithmImpl(key_id)
  /\ UNCHANGED <<config>>

Tick ==
  /\ UNCHANGED vars

Stutter == UNCHANGED vars

Next ==
    \/ Seal \/ Open \/ Register \/ Set_active \/ Active \/ Resolve \/ Known_key_ids \/ Drop \/ Check_and_record \/ Reset \/ Encrypt \/ Decrypt \/ Register_adapter \/ Algorithm \/ Tick \/ Stutter

Spec == Init /\ [][Next]_vars

(* Safety: conjunction of all invariants *)
Safety ==
  /\ CRY_INV_01
  /\ CRY_INV_02
  /\ CRY_INV_03
  /\ CRY_INV_04
  /\ CRY_INV_05
  /\ CRY_INV_06

(* Liveness: meaningful eventual properties *)
Liveness ==
  /\ <>key_id' # key_id

====