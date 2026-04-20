from __future__ import annotations


def upgrade() -> None:
    """Add DESC index on created_at and composite (created_at, id) index."""
    op.create_index('ix_{table}_created_at_cursor', '{table}', [sa.text('created_at DESC')], unique=False)
    op.create_index('ix_{table}_created_at_id_cursor', '{table}', [sa.text('created_at DESC'), sa.text('id DESC')], unique=False)
