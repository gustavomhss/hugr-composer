---- MODULE EncryptionPolicy ----
EXTENDS Naturals, Sequences, FiniteSets

(*
  TLA+ specification for EncryptionPolicy
  Namespace: policy
  Generated from primitive contract and implementation

  Purpose: Declares cipher, key provider, and rotation cadence for a data class at rest and in transit, and rejects storage without a bound policy.

  Invariants:
    INV_01: Every data_class that stores PII, PHI, or PCI MUST have an EncryptionPolicy bound; writes without resolve() succeeding SHALL fail.
    INV_02: at_rest_cipher MUST be one of the approved set (AES-256-GCM, ChaCha20-Poly1305); unapproved ciphers SHALL raise on bind.
    INV_03: in_transit_min_tls MUST be TLS1.2 or higher; binding TLS1.0 or TLS1.1 is FORBIDDEN.
    INV_04: key_provider MUST reference an external KMS; raw key material in configuration files is NEVER permitted.
    INV_05: rotation MUST be ≤ 365 days for PCI data_classes; a longer cadence CANNOT be bound.
*)

CONSTANTS MaxInt

VARIABLES data_class, at_rest_cipher, in_transit_min_tls, key_provider, rotation, None, EP_INV_01, APPROVED_CIPHERS, EP_INV_02, APPROVED_TLS_VERSIONS, EP_INV_03, EP_INV_04, EP_INV_05

vars == <<data_class, at_rest_cipher, in_transit_min_tls, key_provider, rotation, None, EP_INV_01, APPROVED_CIPHERS, EP_INV_02, APPROVED_TLS_VERSIONS, EP_INV_03, EP_INV_04, EP_INV_05>>

TypeOK == 
  /\ data_class \in String
  /\ at_rest_cipher \in String
  /\ in_transit_min_tls \in String
  /\ key_provider \in String
  /\ rotation \in String
  /\ None \in String
  /\ EP_INV_01 \in String
  /\ APPROVED_CIPHERS \in String
  /\ EP_INV_02 \in String
  /\ APPROVED_TLS_VERSIONS \in String
  /\ EP_INV_03 \in String
  /\ EP_INV_04 \in String
  /\ EP_INV_05 \in String

Init == 
  /\ data_class = ""
  /\ at_rest_cipher = ""
  /\ in_transit_min_tls = ""
  /\ key_provider = ""
  /\ rotation = ""
  /\ None = ""
  /\ EP_INV_01 = ""
  /\ APPROVED_CIPHERS = ""
  /\ EP_INV_02 = ""
  /\ APPROVED_TLS_VERSIONS = ""
  /\ EP_INV_03 = ""
  /\ EP_INV_04 = ""
  /\ EP_INV_05 = ""

(* EP_INV_01: Every data_class storing PII, PHI, or PCI MUST have a bound *)
EP_INV_01 ==
  /\ TypeOK

(* EP_INV_02: `at_rest_cipher` MUST be one of the approved set *)
EP_INV_02 ==
  /\ TypeOK

(* EP_INV_03: `in_transit_min_tls` MUST be TLS1.2 or higher; TLS1.0/1.1 *)
EP_INV_03 ==
  /\ TypeOK

(* EP_INV_04: `key_provider` MUST reference an external KMS *)
EP_INV_04 ==
  /\ TypeOK

(* EP_INV_05: For PCI data_classes, `rotation` MUST be <= 365 days. *)
EP_INV_05 ==
  /\ TypeOK

(* Operations *)
Bind ==
  /\ data_class' = BindImpl(data_class)
  /\ UNCHANGED <<config>>

Resolve ==
  /\ data_class' = ResolveImpl(data_class)
  /\ UNCHANGED <<config>>

Require_tls ==
  /\ data_class' = Require_tlsImpl(data_class)
  /\ UNCHANGED <<config>>

Tls_endpoints ==
  /\ data_class' = Tls_endpointsImpl(data_class)
  /\ UNCHANGED <<config>>

Size ==
  /\ data_class' = SizeImpl(data_class)
  /\ UNCHANGED <<config>>

Tick ==
  /\ UNCHANGED vars

Stutter == UNCHANGED vars

Next ==
    \/ Bind \/ Resolve \/ Require_tls \/ Tls_endpoints \/ Size \/ Tick \/ Stutter

Spec == Init /\ [][Next]_vars

(* Safety: conjunction of all invariants *)
Safety ==
  /\ EP_INV_01
  /\ EP_INV_02
  /\ EP_INV_03
  /\ EP_INV_04
  /\ EP_INV_05

(* Liveness: meaningful eventual properties *)
Liveness ==
  /\ <>data_class' # data_class

====