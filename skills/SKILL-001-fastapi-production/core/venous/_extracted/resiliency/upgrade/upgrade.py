from __future__ import annotations


def upgrade() -> None:
    """Create the device_tokens table."""
    op.create_table('device_tokens', sa.Column('id', sa.Uuid(), nullable=False, primary_key=True), sa.Column('user_id', sa.Uuid(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True), sa.Column('platform', sa.String(16), nullable=False), sa.Column('token', sa.String(512), nullable=False), sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False))
