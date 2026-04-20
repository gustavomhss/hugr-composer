from __future__ import annotations


def upgrade() -> None:
    """Create tasks table with owner FK and composite status index."""
    op.create_table('tasks', sa.Column('id', sa.Uuid(), primary_key=True), sa.Column('task_type', sa.String(255), nullable=False), sa.Column('status', sa.String(16), nullable=False, server_default='pending'), sa.Column('owner_id', sa.Uuid(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True), sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False), sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.create_index('ix_tasks_owner_status', 'tasks', ['owner_id', 'status'])
