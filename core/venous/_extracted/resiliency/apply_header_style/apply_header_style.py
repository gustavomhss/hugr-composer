from __future__ import annotations


def apply_header_style(worksheet, row: int=1, num_cols: int=0) -> None:
    """Apply bold, centre-aligned, light-grey background to header cells.

    Args:
        worksheet: Target openpyxl worksheet.
        row: Row number of the header (1-indexed).
        num_cols: Number of columns to style; 0 = auto-detect from row.
    """
    try:
        from openpyxl.styles import Alignment, Font, PatternFill
    except ImportError:
        logger.warning('openpyxl not installed; skipping header style')
        return
    fill = PatternFill(start_color='D3D3D3', end_color='D3D3D3', fill_type='solid')
    font = Font(bold=True)
    alignment = Alignment(horizontal='center')
    col_count = num_cols or worksheet.max_column
    for col in range(1, col_count + 1):
        cell = worksheet.cell(row=row, column=col)
        cell.fill = fill
        cell.font = font
        cell.alignment = alignment
