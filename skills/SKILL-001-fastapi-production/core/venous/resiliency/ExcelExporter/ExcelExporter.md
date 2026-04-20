# ExcelExporter

**Namespace:** `resiliency`
**Maturity:** `emerging`
**Source tool:** `adapt/extend/infrastructure/add_excel_export.py`

## Purpose

`ExcelExporter` wraps `openpyxl.Workbook` with chunked streaming writes
and a hard `max_rows` cap, so a report endpoint can produce large Excel
files without loading all rows into memory and without risk of
runaway exports. `openpyxl` is lazy-imported — the primitive can live
in any codebase regardless of whether `openpyxl` is a runtime dep.

## Invariants

- **EXCEL_EXPORTER_INV_01** — `max_rows` cap: total rows written never
  exceed `max_rows`; the cap raises `ValueError` before writing past
  the limit.
- **EXCEL_EXPORTER_INV_02** — Actionable missing dep: absent `openpyxl`,
  `create_workbook()` raises `ImportError` with a `pip install openpyxl`
  message — never a silent stub.
- **EXCEL_EXPORTER_INV_03** — Chunked writes: n rows are flushed in at
  most `ceil(n / chunk_size)` batches, bounding the memory footprint.

Tests: see `test_ExcelExporter.py`.

## Compose with:

- **Bounded-memory export** → `LoadShedder` + `TimeoutBudget`
  Chunked streaming + max_rows cap + shedder admission means an export request cannot starve general traffic.

- **Observable long work** → `MetricMeter` + `StructuredLogger`
  Chunk counters + duration histograms make export SLOs measurable; a slow export is visible, not anecdotal.

- **Secured output** → `PiiClassification` + `OutputEncoder`
  Rows pass through classification-driven masking before sheet writes — audience-aware exports are mechanical, not a review checklist.
