"""Pure Python primitive: ImportProcessor."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional
import uuid
from datetime import datetime

class ImportProcessor:
    """Parse and process CSV or Excel file data for a given import job.

    Attributes:
        validator: RowValidator applied to every row before insert.
        batch_size: Number of rows committed per transaction.
    """

    def __init__(self, validator: RowValidator | None=None, batch_size: int=500) -> None:
        """Initialise the processor.

        Args:
            validator: Optional row validator (permissive if None).
            batch_size: Rows per DB transaction batch.
        """
        self.validator = validator or RowValidator()
        self.batch_size = batch_size

    def parse_csv(self, content: bytes) -> list[dict[str, Any]]:
        """Parse CSV bytes into a list of row dicts.

        Args:
            content: Raw file bytes (UTF-8 with optional BOM).

        Returns:
            List of row dicts keyed by the header row.
        """
        text = content.decode('utf-8-sig')
        reader = csv.DictReader(io.StringIO(text))
        return [dict(row) for row in reader]

    def parse_excel(self, content: bytes) -> list[dict[str, Any]]:
        """Parse Excel bytes into a list of row dicts (lazy openpyxl).

        Args:
            content: Raw XLSX file bytes.

        Returns:
            List of row dicts keyed by the first-row header values.

        Raises:
            ImportError: If openpyxl is not installed.
        """
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            return []
        headers = [str(h) if h is not None else f'col_{i}' for i, h in enumerate(rows[0])]
        return [dict(zip(headers, row)) for row in rows[1:]]

    def validate_rows(self, rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Split rows into valid and invalid, collecting per-row errors.

        Args:
            rows: Parsed rows from ``parse_csv`` or ``parse_excel``.

        Returns:
            Tuple of (valid_rows, error_rows). Each error row has an
            added ``_errors`` key with a list of error strings.
        """
        valid: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        for idx, row in enumerate(rows):
            row_errors = self.validator.validate(row, idx)
            if row_errors:
                errors.append({**row, '_errors': row_errors})
            else:
                valid.append(row)
        return (valid, errors)

    async def process_batch(self, session: AsyncSession, rows: list[dict[str, Any]]) -> int:
        """Process a batch of valid rows — override to customise persistence.

        Default implementation is a no-op stub; concrete projects override
        this method to insert domain rows via their own CRUD layer.

        Args:
            session: Active async SQLAlchemy session.
            rows: Validated row dicts ready for persistence.

        Returns:
            Number of rows successfully processed.
        """
        logger.debug('process_batch: %d rows (stub — override per domain)', len(rows))
        return len(rows)
