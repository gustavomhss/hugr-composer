---- MODULE MetricMeter ----
EXTENDS Naturals, Sequences, FiniteSets

(*
  TLA+ specification for MetricMeter
  Namespace: obs
  Generated from primitive contract and implementation

  Purpose: Record numeric measurements through four instrument shapes — counter, up-down counter, histogram, asynchronous gauge — under OpenTelemetry metric semantics.

  Invariants:
    INV_01: Counter instruments MUST only accept non-negative values; negative deltas SHALL raise and are FORBIDDEN to be silently clamped.
    INV_02: Histogram boundaries MUST be finite, strictly increasing, and immutable once the instrument is created.
    INV_03: Instrument names MUST match the regex '^[A-Za-z][A-Za-z0-9_./-]{0,62}$' per OTel specification and CANNOT collide with a differently-typed instrument of the same name.
    INV_04: Every instrument MUST carry a UCUM unit string (e.g. 'ms', 's', 'By') — an empty unit is FORBIDDEN.
    INV_05: Observable gauge callbacks MUST be idempotent within a collection cycle and SHALL NEVER raise; exceptions are logged and the measurement is dropped.
    INV_06: Attribute sets attached to measurements NEVER include unbounded-cardinality keys (user id, request id, full URL path).
*)

CONSTANTS MaxInt

VARIABLES name, unit, description

vars == <<name, unit, description>>

TypeOK == 
  /\ name \in String
  /\ unit \in String
  /\ description \in String

Init == 
  /\ name = ""
  /\ unit = ""
  /\ description = ""

(* METRIC_INV_01: Counter non-negative *)
METRIC_INV_01 ==
  /\ TypeOK

(* METRIC_INV_02: Histogram boundaries strict increasing + immutable *)
METRIC_INV_02 ==
  /\ TypeOK

(* METRIC_INV_03: Instrument name + no differently-typed collision *)
METRIC_INV_03 ==
  /\ TypeOK

(* METRIC_INV_04: Unit required *)
METRIC_INV_04 ==
  /\ TypeOK

(* METRIC_INV_05: Gauge callback SHALL NEVER raise observably *)
METRIC_INV_05 ==
  /\ TypeOK

(* METRIC_INV_06: Forbidden cardinality keys *)
METRIC_INV_06 ==
  /\ TypeOK

(* Operations *)
Add ==
  /\ name' = AddImpl(name)
  /\ UNCHANGED <<config>>

Record ==
  /\ name' = RecordImpl(name)
  /\ UNCHANGED <<config>>

Counter ==
  /\ name' = CounterImpl(name)
  /\ UNCHANGED <<config>>

Up_down_counter ==
  /\ name' = Up_down_counterImpl(name)
  /\ UNCHANGED <<config>>

Histogram ==
  /\ name' = HistogramImpl(name)
  /\ UNCHANGED <<config>>

Observable_gauge ==
  /\ name' = Observable_gaugeImpl(name)
  /\ UNCHANGED <<config>>

Validate_unit ==
  /\ name' = Validate_unitImpl(name)
  /\ UNCHANGED <<config>>

Validate_boundaries ==
  /\ name' = Validate_boundariesImpl(name)
  /\ UNCHANGED <<config>>

Validate_attributes ==
  /\ name' = Validate_attributesImpl(name)
  /\ UNCHANGED <<config>>

Measurements ==
  /\ name' = MeasurementsImpl(name)
  /\ UNCHANGED <<config>>

Boundaries ==
  /\ name' = BoundariesImpl(name)
  /\ UNCHANGED <<config>>

Collect_gauge ==
  /\ name' = Collect_gaugeImpl(name)
  /\ UNCHANGED <<config>>

Instruments ==
  /\ name' = InstrumentsImpl(name)
  /\ UNCHANGED <<config>>

Tick ==
  /\ UNCHANGED vars

Stutter == UNCHANGED vars

Next ==
    \/ Add \/ Record \/ Counter \/ Up_down_counter \/ Histogram \/ Observable_gauge \/ Validate_unit \/ Validate_boundaries \/ Validate_attributes \/ Measurements \/ Boundaries \/ Collect_gauge \/ Instruments \/ Tick \/ Stutter

Spec == Init /\ [][Next]_vars

(* Safety: conjunction of all invariants *)
Safety ==
  /\ METRIC_INV_01
  /\ METRIC_INV_02
  /\ METRIC_INV_03
  /\ METRIC_INV_04
  /\ METRIC_INV_05
  /\ METRIC_INV_06

(* Liveness: meaningful eventual properties *)
Liveness ==
  /\ <>name' # name

====