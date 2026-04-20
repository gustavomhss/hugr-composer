from __future__ import annotations


def upgrade() -> None:
    """Create feature_toggles table with index on name."""
    op.create_table('feature_toggles', sa.Column('id', sa.Uuid(), primary_key=True), sa.Column('name', sa.String(127), unique=True, nullable=False), sa.Column('enabled', sa.Boolean(), server_default=sa.false(), nullable=False), sa.Column('rollout_percentage', sa.Integer(), server_default='100', nullable=False), sa.Column('allowed_users', sa.JSON(), server_default='[]', nullable=False), sa.Column('environments', sa.JSON(), server_default='[]', nullable=False), sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False), sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False), sa.CheckConstraint('rollout_percentage BETWEEN 0 AND 100', name='ck_feature_toggles_rollout_range'))
    op.create_index('ix_feature_toggles_name', 'feature_toggles', ['name'], unique=True)
