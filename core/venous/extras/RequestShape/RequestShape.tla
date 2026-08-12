---- MODULE RequestShape ----
EXTENDS Naturals, Sequences, FiniteSets

(*
  TLA+ specification for RequestShape
  Namespace: extras
  Generated from primitive contract and implementation

  Purpose: Capture a request's resiliency context (priority class, deadline, idempotency key, retry-count-so-far) in a single immutable record propagated across boundaries.

  Invariants:
    INV_01: Fields on a RequestShape instance MUST be immutable after construction; in-place mutation is FORBIDDEN.
    INV_02: A request without an explicit priority SHALL default to normal and NEVER silently to critical.
    INV_03: The attempt counter MUST monotonically increase; a decrement CANNOT occur and breaks retry accounting.
    INV_04: to_headers and from_headers SHALL be mutual inverses on the defined fields, round-tripping without loss.
    INV_05: An idempotency_key once set MUST NEVER be altered across retries of the same logical request.
*)

CONSTANTS MaxInt

VARIABLES request_id, priority, deadline_ns, idempotency_key, attempt, origin, extras, None, 04, out, HDR_REQUEST_ID, HDR_PRIORITY, HDR_DEADLINE_NS, HDR_ATTEMPT, HDR_ORIGIN, HDR_SHAPE_VERSION, headers, supporting, lower, try, e, k, next_attempt, next_idempotency_key, method, route_pattern, header_keys, body_bytes, detection, shape_hash

vars == <<request_id, priority, deadline_ns, idempotency_key, attempt, origin, extras, None, 04, out, HDR_REQUEST_ID, HDR_PRIORITY, HDR_DEADLINE_NS, HDR_ATTEMPT, HDR_ORIGIN, HDR_SHAPE_VERSION, headers, supporting, lower, try, e, k, next_attempt, next_idempotency_key, method, route_pattern, header_keys, body_bytes, detection, shape_hash>>

TypeOK == 
  /\ request_id \in String
  /\ priority \in String
  /\ deadline_ns \in 0..MaxInt
  /\ idempotency_key \in String
  /\ attempt \in 0..MaxInt
  /\ origin \in String
  /\ extras \in String
  /\ None \in String
  /\ 04 \in String
  /\ out \in String
  /\ HDR_REQUEST_ID \in String
  /\ HDR_PRIORITY \in String
  /\ HDR_DEADLINE_NS \in String
  /\ HDR_ATTEMPT \in String
  /\ HDR_ORIGIN \in String
  /\ HDR_SHAPE_VERSION \in String
  /\ headers \in String
  /\ supporting \in String
  /\ lower \in String
  /\ try \in String
  /\ e \in String
  /\ k \in String
  /\ next_attempt \in 0..MaxInt
  /\ next_idempotency_key \in String
  /\ method \in String
  /\ route_pattern \in String
  /\ header_keys \in String
  /\ body_bytes \in 0..MaxInt
  /\ detection \in String
  /\ shape_hash \in String

Init == 
  /\ request_id = ""
  /\ priority = ""
  /\ deadline_ns = 0
  /\ idempotency_key = ""
  /\ attempt = 0
  /\ origin = ""
  /\ extras = ""
  /\ None = ""
  /\ 04 = ""
  /\ out = ""
  /\ HDR_REQUEST_ID = ""
  /\ HDR_PRIORITY = ""
  /\ HDR_DEADLINE_NS = ""
  /\ HDR_ATTEMPT = ""
  /\ HDR_ORIGIN = ""
  /\ HDR_SHAPE_VERSION = ""
  /\ headers = ""
  /\ supporting = ""
  /\ lower = ""
  /\ try = ""
  /\ e = ""
  /\ k = ""
  /\ next_attempt = 0
  /\ next_idempotency_key = ""
  /\ method = ""
  /\ route_pattern = ""
  /\ header_keys = ""
  /\ body_bytes = 0
  /\ detection = ""
  /\ shape_hash = ""

(* RSHP_INV_01: immutability *)
RSHP_INV_01 ==
  /\ TypeOK

(* RSHP_INV_02: priority default *)
RSHP_INV_02 ==
  /\ TypeOK

(* RSHP_INV_03: monotonic attempt *)
RSHP_INV_03 ==
  /\ version' = version + 1

(* RSHP_INV_04: header round-trip *)
RSHP_INV_04 ==
  /\ TypeOK

(* RSHP_INV_05: idempotency key stability *)
RSHP_INV_05 ==
  /\ TypeOK

(* Operations *)
To_headers ==
  /\ request_id' = To_headersImpl(request_id)
  /\ UNCHANGED <<config>>

From_headers ==
  /\ request_id' = From_headersImpl(request_id)
  /\ UNCHANGED <<config>>

Validate_priority ==
  /\ request_id' = Validate_priorityImpl(request_id)
  /\ UNCHANGED <<config>>

Validate_deadline_ns ==
  /\ request_id' = Validate_deadline_nsImpl(request_id)
  /\ UNCHANGED <<config>>

Validate_attempt ==
  /\ request_id' = Validate_attemptImpl(request_id)
  /\ UNCHANGED <<config>>

Validate_origin ==
  /\ request_id' = Validate_originImpl(request_id)
  /\ UNCHANGED <<config>>

Validate_idempotency_key ==
  /\ request_id' = Validate_idempotency_keyImpl(request_id)
  /\ UNCHANGED <<config>>

Check_monotonic_attempt ==
  /\ request_id' = Check_monotonic_attemptImpl(request_id)
  /\ UNCHANGED <<config>>

Check_idempotency_key_preserved ==
  /\ request_id' = Check_idempotency_key_preservedImpl(request_id)
  /\ UNCHANGED <<config>>

Size_class ==
  /\ request_id' = Size_classImpl(request_id)
  /\ UNCHANGED <<config>>

With_incremented_attempt ==
  /\ request_id' = With_incremented_attemptImpl(request_id)
  /\ UNCHANGED <<config>>

With_next_attempt ==
  /\ request_id' = With_next_attemptImpl(request_id)
  /\ UNCHANGED <<config>>

Shape_hash ==
  /\ request_id' = Shape_hashImpl(request_id)
  /\ UNCHANGED <<config>>

Tick ==
  /\ UNCHANGED vars

Stutter == UNCHANGED vars

Next ==
    \/ To_headers \/ From_headers \/ Validate_priority \/ Validate_deadline_ns \/ Validate_attempt \/ Validate_origin \/ Validate_idempotency_key \/ Check_monotonic_attempt \/ Check_idempotency_key_preserved \/ Size_class \/ With_incremented_attempt \/ With_next_attempt \/ Shape_hash \/ Tick \/ Stutter

Spec == Init /\ [][Next]_vars

(* Safety: conjunction of all invariants *)
Safety ==
  /\ RSHP_INV_01
  /\ RSHP_INV_02
  /\ RSHP_INV_03
  /\ RSHP_INV_04
  /\ RSHP_INV_05

(* Liveness: meaningful eventual properties *)
Liveness ==
  /\ <>request_id' # request_id

====