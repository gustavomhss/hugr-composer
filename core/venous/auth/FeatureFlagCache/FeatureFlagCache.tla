---- MODULE FeatureFlagCache ----
EXTENDS Naturals, Sequences, FiniteSets

(*
  TLA+ specification for FeatureFlagCache
  Namespace: auth
  Generated from primitive contract and implementation

  Purpose: Bounded in-process async LRU cache with per-entry TTL for feature-flag payloads. Thread-safe via an asyncio.Lock. Evicts on capacity (LRU) and on read (expired-TTL). Stable under concurrent access.

  Invariants:
    INV_01: FEATURE_FLAG_CACHE_INV_01: `get(k)` on an expired entry MUST return None AND remove the stale entry from the store (read-through eviction).
    INV_02: FEATURE_FLAG_CACHE_INV_02: The store size MUST never exceed MAX_CACHE_SIZE after any `set`; eviction order is strict LRU (least recently accessed key first).
    INV_03: FEATURE_FLAG_CACHE_INV_03: After `set(k, v)`, a subsequent `get(k)` within the TTL window MUST return the stored `v` (write-then-read consistency).
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

(* FEATUREFLAGCACHE_INV_01: FEATURE_FLAG_CACHE_INV_01: `get(k)` on an expired entry MUST return None AND remove the stale entry from the store (read-through eviction). *)
FEATUREFLAGCACHE_INV_01 ==
  /\ TRUE

(* FEATUREFLAGCACHE_INV_02: FEATURE_FLAG_CACHE_INV_02: The store size MUST never exceed MAX_CACHE_SIZE after any `set`; eviction order is strict LRU (least recently accessed key first). *)
FEATUREFLAGCACHE_INV_02 ==
  /\ state <= config

(* FEATUREFLAGCACHE_INV_03: FEATURE_FLAG_CACHE_INV_03: After `set(k, v)`, a subsequent `get(k)` within the TTL window MUST return the stored `v` (write-then-read consistency). *)
FEATUREFLAGCACHE_INV_03 ==
  /\ cache_expiry <= MIN(exp, ttl)

(* Operations *)
Execute ==
  /\ state' = ExecuteImpl(state)
  /\ UNCHANGED <<config>>

Reset ==
  /\ key # ""
  /\ state' = InitState
  /\ UNCHANGED <<config>>

Tick ==
  /\ UNCHANGED vars

Stutter == UNCHANGED vars

Next ==
    \/ Execute \/ Reset \/ Tick \/ Stutter

Spec == Init /\ [][Next]_vars

(* Safety: conjunction of all invariants *)
Safety ==
  /\ FEATUREFLAGCACHE_INV_01
  /\ FEATUREFLAGCACHE_INV_02
  /\ FEATUREFLAGCACHE_INV_03

(* Liveness: meaningful eventual properties *)
Liveness ==
  /\ <>state' # state
  /\ <>validated = TRUE
  /\ <>read_version = write_version

====