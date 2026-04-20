from __future__ import annotations


def auto_fit_columns(worksheet, min_width: int=8, max_width: int=60) -> None:
    """Set column widths based on the maximum content length per column.

    Args:
        worksheet: Target openpyxl worksheet.
        min_width: Minimum column width in character units.
        max_width: Maximum column width cap to prevent overly wide columns.
    """
    col_widths: dict[str, int] = {}
    for row in worksheet.iter_rows():
        for cell in row:
            col_letter = cell.column_letter
            value_len = len(str(cell.value)) if cell.value is not None else 0
            current = col_widths.get(col_letter, min_width)
            col_widths[col_letter] = min(max(current, value_len + 2), max_width)
    for col_letter, width in col_widths.items():
        worksheet.column_dimensions[col_letter].width = width
