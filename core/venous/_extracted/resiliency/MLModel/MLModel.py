from __future__ import annotations
from datetime import datetime
import uuid


class MLModel(Base):
    """A versioned ML model artefact entry in the registry.

    Attributes:
        id: Internal UUID primary key.
        name: Logical model name (e.g. ``"fraud_detector"``).
        version: Semantic version string (e.g. ``"1.2.3"``).
        artifact_path: Filesystem or object-storage path to the artefact.
        framework: Framework name string (e.g. ``"sklearn"``, ``"pytorch"``).
        metrics_json: Free-form JSON with accuracy, f1, latency, etc.
        status: Lifecycle status — one of ``registered``, ``staging``,
            ``production``, ``archived``, ``rolled_back``.
        promoted_at: UTC timestamp when this version entered production.
        created_at: UTC timestamp when the row was inserted.
    """
    __tablename__ = 'ml_models'
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    artifact_path: Mapped[str] = mapped_column(String(512), nullable=False, default='')
    framework: Mapped[str] = mapped_column(String(64), nullable=False, default='unknown')
    metrics_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default='registered', index=True)
    promoted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    __table_args__ = (Index('ix_ml_models_name_version', 'name', 'version', unique=True),)
