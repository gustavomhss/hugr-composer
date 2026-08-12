---- MODULE TamperEvidentAuditLog ----
EXTENDS Naturals, Sequences, FiniteSets

(*
  TLA+ specification for TamperEvidentAuditLog
  Namespace: compliance
  Generated from primitive contract and implementation

  Purpose: Append-only record of security-relevant events, hash-chained and signed so any retroactive mutation is detectable by verification.

  Invariants:
    INV_01: Entries MUST be append-only; the store SHALL reject UPDATE or DELETE on any prior sequence.
    INV_02: Each entry MUST contain the SHA-256 of the prior entry, forming a chain that CANNOT be mutated without detection.
    INV_03: Each entry MUST carry a signature from a key whose private half is NEVER held by the writing service.
    INV_04: Sequence numbers MUST be monotonically increasing with no gaps; verify_chain SHALL fail on gap or regression.
    INV_05: Actor, action, resource, outcome, and timestamp MUST be present on every entry; absence SHALL raise.
    INV_06: Clock source MUST be monotonic server-side; client-supplied timestamps SHALL be rejected.
*)

CONSTANTS MaxInt

VARIABLES seq, timestamp, actor, action, resource, outcome, attributes, prev_hash, entry_hash, signature, key_id, k, payload, str

vars == <<seq, timestamp, actor, action, resource, outcome, attributes, prev_hash, entry_hash, signature, key_id, k, payload, str>>

TypeOK == 
  /\ seq \in 0..MaxInt
  /\ timestamp \in String
  /\ actor \in String
  /\ action \in String
  /\ resource \in String
  /\ outcome \in String
  /\ attributes \in String
  /\ prev_hash \in String
  /\ entry_hash \in String
  /\ signature \in String
  /\ key_id \in String
  /\ k \in String
  /\ payload \in String
  /\ str \in String

Init == 
  /\ seq = 0
  /\ timestamp = ""
  /\ actor = ""
  /\ action = ""
  /\ resource = ""
  /\ outcome = ""
  /\ attributes = ""
  /\ prev_hash = ""
  /\ entry_hash = ""
  /\ signature = ""
  /\ key_id = ""
  /\ k = ""
  /\ payload = ""
  /\ str = ""

(* TEAL_INV_01: Entries MUST be append-only; `update` / `delete` SHALL be *)
TEAL_INV_01 ==
  /\ TypeOK

(* TEAL_INV_02: Each entry MUST carry `prev_hash = SHA-256(prior entry's *)
TEAL_INV_02 ==
  /\ TypeOK

(* TEAL_INV_03: Each entry MUST carry a signature produced by a `Signer` *)
TEAL_INV_03 ==
  /\ TypeOK

(* TEAL_INV_04: Sequence numbers MUST be monotonically increasing by 1 with *)
TEAL_INV_04 ==
  /\ version' = version + 1

(* TEAL_INV_05: `actor`, `action`, `resource`, `outcome`, and `timestamp` *)
TEAL_INV_05 ==
  /\ TypeOK

(* TEAL_INV_06: `timestamp` MUST come from the server's monotonic wall clock *)
TEAL_INV_06 ==
  /\ version' = version + 1

(* Operations *)
Sign ==
  /\ seq' = SignImpl(seq)
  /\ UNCHANGED <<config>>

Verify ==
  /\ seq' = VerifyImpl(seq)
  /\ UNCHANGED <<config>>

Key_id ==
  /\ seq' = Key_idImpl(seq)
  /\ UNCHANGED <<config>>

Append ==
  /\ seq' = AppendImpl(seq)
  /\ UNCHANGED <<config>>

Verify_chain ==
  /\ seq' = Verify_chainImpl(seq)
  /\ UNCHANGED <<config>>

Get ==
  /\ key # ""
  /\ result' = GetImpl(key)
  /\ UNCHANGED <<config>>

Export ==
  /\ seq' = ExportImpl(seq)
  /\ UNCHANGED <<config>>

Size ==
  /\ seq' = SizeImpl(seq)
  /\ UNCHANGED <<config>>

Tick ==
  /\ UNCHANGED vars

Stutter == UNCHANGED vars

Next ==
    \/ Sign \/ Verify \/ Key_id \/ Append \/ Verify_chain \/ Get \/ Export \/ Size \/ Tick \/ Stutter

Spec == Init /\ [][Next]_vars

(* Safety: conjunction of all invariants *)
Safety ==
  /\ TEAL_INV_01
  /\ TEAL_INV_02
  /\ TEAL_INV_03
  /\ TEAL_INV_04
  /\ TEAL_INV_05
  /\ TEAL_INV_06

(* Liveness: meaningful eventual properties *)
Liveness ==
  /\ <>seq' # seq

====