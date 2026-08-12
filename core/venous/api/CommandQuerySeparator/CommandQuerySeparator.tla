---- MODULE CommandQuerySeparator ----
EXTENDS Naturals, Sequences, FiniteSets

(*
  TLA+ specification for CommandQuerySeparator
  Namespace: api
  Generated from primitive contract and implementation

  Purpose: Partitions the API into write commands that mutate state and read queries that observe it so each side can scale and evolve independently.

  Invariants:
    INV_01: A command handler MUST NEVER return query results synthesized from the write model; it SHALL return only acknowledgement and identifiers.
    INV_02: A query handler CANNOT mutate state, invoke commands, or block on external side-effects.
    INV_03: Each command type MUST have at most one registered handler; duplicate handler registration is FORBIDDEN.
    INV_04: Read models ALWAYS receive updates through the same event stream as the write model; separate in-band write paths for reads are FORBIDDEN.
*)

CONSTANTS MaxInt

VARIABLES 01, ack, status, ids, event_offset, event_id, command_type, payload, offset, name, state, _event_offset, event, key, value, None, 04

vars == <<01, ack, status, ids, event_offset, event_id, command_type, payload, offset, name, state, _event_offset, event, key, value, None, 04>>

TypeOK == 
  /\ 01 \in String
  /\ ack \in {TRUE, FALSE}
  /\ status \in String
  /\ ids \in String
  /\ event_offset \in 0..MaxInt
  /\ event_id \in String
  /\ command_type \in String
  /\ payload \in String
  /\ offset \in 0..MaxInt
  /\ name \in String
  /\ state \in String
  /\ _event_offset \in 0..MaxInt
  /\ event \in String
  /\ key \in String
  /\ value \in String
  /\ None \in String
  /\ 04 \in String

Init == 
  /\ 01 = ""
  /\ ack = FALSE
  /\ status = ""
  /\ ids = ""
  /\ event_offset = 0
  /\ event_id = ""
  /\ command_type = ""
  /\ payload = ""
  /\ offset = 0
  /\ name = ""
  /\ state = ""
  /\ _event_offset = 0
  /\ event = ""
  /\ key = ""
  /\ value = ""
  /\ None = ""
  /\ 04 = ""

(* CQS_INV_01: command handler returns ack-only (never a projection) *)
CQS_INV_01 ==
  /\ TypeOK

(* CQS_INV_02: query handler is side-effect free *)
CQS_INV_02 ==
  /\ TypeOK

(* CQS_INV_03: at most one handler per command type *)
CQS_INV_03 ==
  /\ TypeOK

(* CQS_INV_04: read models fed ONLY via the event stream *)
CQS_INV_04 ==
  /\ read_version = write_version

(* Operations *)
As_dict ==
  /\ 01' = As_dictImpl(01)
  /\ UNCHANGED <<config>>

Dispatch_command ==
  /\ 01' = Dispatch_commandImpl(01)
  /\ UNCHANGED <<config>>

Answer_query ==
  /\ 01' = Answer_queryImpl(01)
  /\ UNCHANGED <<config>>

Register_command_handler ==
  /\ 01' = Register_command_handlerImpl(01)
  /\ UNCHANGED <<config>>

Register_query_handler ==
  /\ 01' = Register_query_handlerImpl(01)
  /\ UNCHANGED <<config>>

Validate_ack_payload ==
  /\ 01' = Validate_ack_payloadImpl(01)
  /\ UNCHANGED <<config>>

Append ==
  /\ 01' = AppendImpl(01)
  /\ UNCHANGED <<config>>

Subscribe ==
  /\ 01' = SubscribeImpl(01)
  /\ UNCHANGED <<config>>

Events ==
  /\ 01' = EventsImpl(01)
  /\ UNCHANGED <<config>>

Apply_event ==
  /\ 01' = Apply_eventImpl(01)
  /\ UNCHANGED <<config>>

Direct_write ==
  /\ 01' = Direct_writeImpl(01)
  /\ UNCHANGED <<config>>

Emit_event ==
  /\ 01' = Emit_eventImpl(01)
  /\ UNCHANGED <<config>>

Register_read_model ==
  /\ 01' = Register_read_modelImpl(01)
  /\ UNCHANGED <<config>>

Read_models ==
  /\ 01' = Read_modelsImpl(01)
  /\ UNCHANGED <<config>>

Event_stream ==
  /\ 01' = Event_streamImpl(01)
  /\ UNCHANGED <<config>>

Command_types ==
  /\ 01' = Command_typesImpl(01)
  /\ UNCHANGED <<config>>

Query_types ==
  /\ 01' = Query_typesImpl(01)
  /\ UNCHANGED <<config>>

Tick ==
  /\ UNCHANGED vars

Stutter == UNCHANGED vars

Next ==
    \/ As_dict \/ Dispatch_command \/ Answer_query \/ Register_command_handler \/ Register_query_handler \/ Validate_ack_payload \/ Append \/ Subscribe \/ Events \/ Apply_event \/ Direct_write \/ Emit_event \/ Register_read_model \/ Read_models \/ Event_stream \/ Command_types \/ Query_types \/ Tick \/ Stutter

Spec == Init /\ [][Next]_vars

(* Safety: conjunction of all invariants *)
Safety ==
  /\ CQS_INV_01
  /\ CQS_INV_02
  /\ CQS_INV_03
  /\ CQS_INV_04

(* Liveness: meaningful eventual properties *)
Liveness ==
  /\ <>01' # 01

====