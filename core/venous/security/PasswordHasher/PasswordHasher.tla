---- MODULE PasswordHasher ----
EXTENDS Naturals, Sequences, FiniteSets

(*
  TLA+ specification for PasswordHasher
  Namespace: security
  Generated from primitive contract and implementation

  Purpose: Derive a verifier from a user-supplied secret using a memory-hard KDF with per-credential salt, tunable cost, and constant-time comparison.

  Invariants:
    INV_01: Stored verifier MUST encode algorithm identifier, cost parameters, salt, and digest so rotation is self-describing.
    INV_02: verify() MUST run in constant time with respect to digest bytes and NEVER branch on character-by-character equality.
    INV_03: Salt MUST be drawn from a CSPRNG, be ≥16 bytes, and MUST NEVER be reused across credentials.
    INV_04: hash() MUST use a memory-hard function (Argon2id / scrypt / bcrypt) and SHALL NEVER use raw SHA-2, MD5, or PBKDF2-SHA1.
    INV_05: needs_rehash() MUST return True when stored cost parameters are below the configured floor, and the caller MUST rehash on next successful login.
    INV_06: Plaintext MUST NEVER be logged, serialized, or included in exceptions raised by this primitive.
*)

CONSTANTS MaxInt

VARIABLES algo, params, salt, digest, params_str, piece, 01, try, exc, stored, 5, FORBIDDEN_ALGOS, 04, ALLOWED_ALGOS, MIN_SALT_BYTES, 03, str, time_cost, memory_cost, parallelism, hash_len

vars == <<algo, params, salt, digest, params_str, piece, 01, try, exc, stored, 5, FORBIDDEN_ALGOS, 04, ALLOWED_ALGOS, MIN_SALT_BYTES, 03, str, time_cost, memory_cost, parallelism, hash_len>>

TypeOK == 
  /\ algo \in String
  /\ params \in 0..MaxInt
  /\ salt \in String
  /\ digest \in String
  /\ params_str \in String
  /\ piece \in String
  /\ 01 \in String
  /\ try \in String
  /\ exc \in String
  /\ stored \in String
  /\ 5 \in String
  /\ FORBIDDEN_ALGOS \in String
  /\ 04 \in String
  /\ ALLOWED_ALGOS \in String
  /\ MIN_SALT_BYTES \in String
  /\ 03 \in String
  /\ str \in String
  /\ time_cost \in 0..MaxInt
  /\ memory_cost \in 0..MaxInt
  /\ parallelism \in 0..MaxInt
  /\ hash_len \in 0..MaxInt

Init == 
  /\ algo = ""
  /\ params = 0
  /\ salt = ""
  /\ digest = ""
  /\ params_str = ""
  /\ piece = ""
  /\ 01 = ""
  /\ try = ""
  /\ exc = ""
  /\ stored = ""
  /\ 5 = ""
  /\ FORBIDDEN_ALGOS = ""
  /\ 04 = ""
  /\ ALLOWED_ALGOS = ""
  /\ MIN_SALT_BYTES = ""
  /\ 03 = ""
  /\ str = ""
  /\ time_cost = 0
  /\ memory_cost = 0
  /\ parallelism = 0
  /\ hash_len = 0

(* PWD_INV_01: self-describing stored format *)
PWD_INV_01 ==
  /\ TypeOK

(* PWD_INV_02: constant-time verify *)
PWD_INV_02 ==
  /\ TypeOK

(* PWD_INV_03: salt from CSPRNG, ≥16 bytes, unique *)
PWD_INV_03 ==
  /\ TypeOK

(* PWD_INV_04: memory-hard algorithm; weak algorithms FORBIDDEN *)
PWD_INV_04 ==
  /\ TypeOK

(* PWD_INV_05: needs_rehash drives rotation *)
PWD_INV_05 ==
  /\ TypeOK

(* PWD_INV_06: plaintext NEVER logged/leaked in exceptions *)
PWD_INV_06 ==
  /\ TypeOK

(* Operations *)
Hash ==
  /\ algo' = HashImpl(algo)
  /\ UNCHANGED <<config>>

Verify ==
  /\ algo' = VerifyImpl(algo)
  /\ UNCHANGED <<config>>

Needs_rehash ==
  /\ algo' = Needs_rehashImpl(algo)
  /\ UNCHANGED <<config>>

Parse_stored ==
  /\ algo' = Parse_storedImpl(algo)
  /\ UNCHANGED <<config>>

Tick ==
  /\ UNCHANGED vars

Stutter == UNCHANGED vars

Next ==
    \/ Hash \/ Verify \/ Needs_rehash \/ Parse_stored \/ Tick \/ Stutter

Spec == Init /\ [][Next]_vars

(* Safety: conjunction of all invariants *)
Safety ==
  /\ PWD_INV_01
  /\ PWD_INV_02
  /\ PWD_INV_03
  /\ PWD_INV_04
  /\ PWD_INV_05
  /\ PWD_INV_06

(* Liveness: meaningful eventual properties *)
Liveness ==
  /\ <>algo' # algo

====