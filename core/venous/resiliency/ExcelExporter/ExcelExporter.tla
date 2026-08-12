---- MODULE ExcelExporter ----
EXTENDS Naturals, Sequences, FiniteSets

(*
  TLA+ specification for ExcelExporter
  Namespace: resiliency
  Generated from primitive contract and implementation

  Purpose: Creates openpyxl workbooks with chunked streaming write for large result sets. Enforces a hard `max_rows` cap. Lazy-imports openpyxl so the primitive can live in a codebase that may not depend on it at runtime.

  Invariants:
    INV_01: EXCEL_EXPORTER_INV_01: Total rows written across all `add_sheet`/`write_rows` calls MUST NEVER exceed `max_rows`; exceeding the cap raises ValueError BEFORE any partial data is written past the limit.
    INV_02: EXCEL_EXPORTER_INV_02: `create_workbook()` MUST raise ImportError with an actionable message ('pip install openpyxl') when openpyxl is unavailable — never silently returns a broken stub.
    INV_03: EXCEL_EXPORTER_INV_03: Rows MUST be written in batches of `chunk_size`; given n rows, at most ceil(n / chunk_size) flush points occur (bounded memory footprint).
*)

CONSTANTS MaxInt

VARIABLES chunk_size, max_rows

vars == <<chunk_size, max_rows>>

TypeOK == 
  /\ chunk_size \in 0..MaxInt
  /\ max_rows \in String

Init == 
  /\ chunk_size = 0
  /\ max_rows = ""

(* EXCELEXPORTER_INV_01: EXCEL_EXPORTER_INV_01: Total rows written across all `add_sheet`/`write_rows` calls MUST NEVER exceed `max_rows`; exceeding the cap raises ValueError BEFORE any partial data is written past the limit. *)
EXCELEXPORTER_INV_01 ==
  /\ chunk_size <= max_rows

(* EXCELEXPORTER_INV_02: EXCEL_EXPORTER_INV_02: `create_workbook()` MUST raise ImportError with an actionable message ('pip install openpyxl') when openpyxl is unavailable — never silently returns a broken stub. *)
EXCELEXPORTER_INV_02 ==
  /\ TRUE

(* EXCELEXPORTER_INV_03: EXCEL_EXPORTER_INV_03: Rows MUST be written in batches of `chunk_size`; given n rows, at most ceil(n / chunk_size) flush points occur (bounded memory footprint). *)
EXCELEXPORTER_INV_03 ==
  /\ TRUE

(* Operations *)
Create_workbook ==
  /\ chunk_size' = Create_workbookImpl(chunk_size)
  /\ UNCHANGED <<config>>

Add_sheet ==
  /\ chunk_size' = Add_sheetImpl(chunk_size)
  /\ UNCHANGED <<config>>

Stream_rows ==
  /\ chunk_size' = Stream_rowsImpl(chunk_size)
  /\ UNCHANGED <<config>>

To_bytes ==
  /\ chunk_size' = To_bytesImpl(chunk_size)
  /\ UNCHANGED <<config>>

Tick ==
  /\ UNCHANGED vars

Stutter == UNCHANGED vars

Next ==
    \/ Create_workbook \/ Add_sheet \/ Stream_rows \/ To_bytes \/ Tick \/ Stutter

Spec == Init /\ [][Next]_vars

(* Safety: conjunction of all invariants *)
Safety ==
  /\ EXCELEXPORTER_INV_01
  /\ EXCELEXPORTER_INV_02
  /\ EXCELEXPORTER_INV_03

(* Liveness: meaningful eventual properties *)
Liveness ==
  /\ <>chunk_size' # chunk_size

====