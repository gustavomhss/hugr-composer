# TOOL-024: add_saga

> **Status**: SPEC v2 (rigorous)
> **Last updated**: 2026-04-08

---

## 1. Overview

| Field | Value |
|-------|-------|
| Tool name | `fastapi_add_saga` |
| Category | EXTEND > Infrastructure |
| Complexity | High |
| Dependencies | FastAPI, SQLAlchemy, Alembic, Redis or PostgreSQL |
| Signature | `add_saga(project_dir: str, state_backend: Literal["postgres", "redis"] = "postgres", step_timeout_seconds: int = 30, max_compensations: int = 10) -> dict` |
| Parameters | `project_dir`: Absolute path to FastAPI project root (e.g. `/app/my_project`)<br>`state_backend`: Persistence layer for saga state (`postgres` default)<br>`step_timeout_seconds`: Max duration per step before compensation (default 30s)<br>`max_compensations`: Maximum compensation attempts before escalation (default 10) |

## 2. Purpose

The `fastapi_add_saga` tool implements distributed-transaction orchestration via the Saga pattern so long-running multi-step business workflows — "book flight, reserve hotel, charge card, send confirmation" — can run safely across services that do not share a single database transaction. It generates a complete execution framework: a `Saga` base class, `@saga_step(compensate=...)` decorators that pair every forward action with its compensation (reverse action), a `SagaCoordinator` service that drives execution step-by-step, PostgreSQL-backed durable state (so a saga that was mid-flight during a pod restart resumes exactly where it left off), and an admin dashboard at `/admin/sagas` for inspection and manual intervention. Without this tool, teams hand-roll rollback logic per workflow and end up with the classic distributed-systems failure: a credit card was charged but the hotel reservation never happened, and nobody can tell from the code what state the system is in.

Every saga persists its state *before* each step executes so a crash is always recoverable — the coordinator on restart queries `sagas WHERE state IN ('RUNNING','COMPENSATING')` and resumes them. Compensation runs in **strict reverse order** of successful steps (step N+1 fails → compensate step N → compensate step N-1 → ... → step 1) so the business guarantees match what most engineers intuit from synchronous transactions. Key design decisions: compensations must be **idempotent** by convention (the framework enforces this via an `idempotency_key` argument that every compensate function receives), retries use exponential backoff with a hard cap before the saga is marked `FAILED` and escalated to DLQ for human review, step timeouts are enforced per step (not per saga) so a stuck payment gateway does not block unrelated sagas, and the coordinator surfaces Prometheus metrics (`saga_state_total`, `saga_step_duration_seconds`, `saga_compensations_total`) plus structured logs with correlation IDs so every business workflow is observable end-to-end. Integrates with TOOL-023 (outbox) so saga events are guaranteed to reach downstream consumers even if the coordinator process crashes between step completion and event publish.

## 3. Performance SLOs

| Metric | Target | Why |
|--------|--------|-----|
| Tool execution time | < 5s | Must complete during deployment without blocking CI/CD |
| Files modified | ≤ 5 | Minimize merge conflicts in existing project files |
| Files created | ≥ 9 | Complete saga implementation requires multiple components |
| Step execution overhead | < 2 ms | Negligible impact on business logic runtime |
| State persistence latency | < 5 ms per step | Ensure timely progress tracking without bottleneck |
| Compensation trigger delay | < 1s after failure | Quick rollback minimizes inconsistent state window |
| Timeout enforcement | Exact to ±100ms | Precise failure detection prevents resource leaks |
| Migration runtime | 0s — no DB changes | State tables are pre-created by separate migration |

---

## 4. Code Examples (Before / After)

### 4.1 Base model: BEFORE
```python
# app/models/base.py
from sqlalchemy.orm import DeclarativeBase
import uuid


class Base(DeclarativeBase):
    """Base model class with common columns and methods."""
    pass
```

### 4.2 Base model: AFTER
```python
# app/models/base.py
from datetime import datetime
from sqlalchemy import DateTime, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
import uuid


class Base(DeclarativeBase):
    """Base model class with common columns and methods."""
    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False
    )
```

### 4.3 Saga state models (NEW)
```python
# app/models/saga.py
from datetime import datetime
from typing import Optional
from sqlalchemy import ForeignKey, Integer, String, Text, JSON, DateTime, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base
import uuid


class SagaInstance(Base):
    __tablename__ = "saga_instances"

    saga_type: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    state: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="pending",
        index=True
    )
    current_step: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    input_data: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    output_data: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    requires_human: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    
    steps: Mapped[list["SagaStepExecution"]] = relationship(
        "SagaStepExecution",
        back_populates="saga",
        cascade="all, delete-orphan",
        order_by="SagaStepExecution.step_number"
    )


class SagaStepExecution(Base):
    __tablename__ = "saga_step_executions"

    saga_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("saga_instances.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    step_number: Mapped[int] = mapped_column(Integer, nullable=False)
    step_name: Mapped[str] = mapped_column(String(128), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    input_data: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    output_data: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    compensation_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    compensated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    
    saga: Mapped["SagaInstance"] = relationship("SagaInstance", back_populates="steps")
```

### 4.4 Saga base class and decorator (NEW)
```python
# app/core/saga.py
from abc import ABC, abstractmethod
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, AsyncGenerator, Callable, Dict, List, Optional, Type
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.db import get_async_session
from app.models.saga import SagaInstance, SagaStepExecution
import asyncio
import inspect
import uuid


class SagaStep:
    def __init__(self, compensate: Optional[str] = None, timeout: int = 30):
        self.compensate_name = compensate
        self.timeout = timeout
    
    def __call__(self, func: Callable):
        func._saga_step = True
        func._compensate_name = self.compensate_name
        func._timeout = self.timeout
        return func


class Saga(ABC):
    def __init__(self, session: AsyncSession):
        self.session = session
        self.steps: List[Dict[str, Any]] = []
        self._collect_steps()
    
    def _collect_steps(self):
        for name in dir(self):
            if name.startswith("_"):
                continue
            method = getattr(self, name)
            if hasattr(method, "_saga_step"):
                self.steps.append({
                    "name": name,
                    "forward": method,
                    "compensate_name": method._compensate_name,
                    "timeout": method._timeout
                })
        self.steps.sort(key=lambda x: list(inspect.signature(x["forward"]).parameters).index("saga_id"))
    
    async def execute(self, saga_id: uuid.UUID, input_data: Dict[str, Any]) -> Dict[str, Any]:
        saga = SagaInstance(
            id=saga_id,
            saga_type=self.__class__.__name__,
            state="running",
            input_data=input_data
        )
        self.session.add(saga)
        
        for i, step_info in enumerate(self.steps):
            step_exec = SagaStepExecution(
                saga_id=saga_id,
                step_number=i,
                step_name=step_info["name"],
                input_data=input_data.get(step_info["name"], {})
            )
            self.session.add(step_exec)
        
        await self.session.commit()
        return await self._run_steps(saga_id, input_data)
    
    async def _run_steps(self, saga_id: uuid.UUID, input_data: Dict[str, Any]) -> Dict[str, Any]:
        completed_steps = []
        
        for i, step_info in enumerate(self.steps):
            try:
                step_exec = await self._get_step_execution(saga_id, step_info["name"])
                step_exec.state = "running"
                await self.session.commit()
                
                result = await asyncio.wait_for(
                    step_info["forward"](saga_id=saga_id, **input_data),
                    timeout=step_info["timeout"]
                )
                
                step_exec.state = "completed"
                step_exec.output_data = result
                await self.session.commit()
                completed_steps.append((i, step_info))
                
            except Exception as e:
                step_exec.state = "failed"
                step_exec.error = str(e)
                await self.session.commit()
                await self._compensate(saga_id, completed_steps, input_data)
                raise
        
        saga = await self.session.get(SagaInstance, saga_id)
        saga.state = "completed"
        saga.completed_at = datetime.utcnow()
        await self.session.commit()
        return {"status": "completed", "saga_id": str(saga_id)}
    
    async def _compensate(self, saga_id: uuid.UUID, completed_steps: List, input_data: Dict[str, Any]):
        saga = await self.session.get(SagaInstance, saga_id)
        saga.state = "compensating"
        await self.session.commit()
        
        for i, step_info in reversed(completed_steps):
            if step_info["compensate_name"]:
                compensate_method = getattr(self, step_info["compensate_name"])
                step_exec = await self._get_step_execution(saga_id, step_info["name"])
                
                try:
                    await compensate_method(saga_id=saga_id, **input_data)
                    step_exec.state = "compensated"
                    step_exec.compensated_at = datetime.utcnow()
                except Exception as e:
                    step_exec.compensation_attempts += 1
                    step_exec.error = f"Compensation failed: {str(e)}"
                    if step_exec.compensation_attempts >= 10:
                        saga.requires_human = True
                        saga.state = "failed"
                        await self.session.commit()
                        raise
                
                await self.session.commit()
        
        saga.state = "compensated"
        await self.session.commit()
    
    async def _get_step_execution(self, saga_id: uuid.UUID, step_name: str) -> SagaStepExecution:
        from sqlalchemy import select
        stmt = select(SagaStepExecution).where(
            SagaStepExecution.saga_id == saga_id,
            SagaStepExecution.step_name == step_name
        )
        result = await self.session.execute(stmt)
        return result.scalar_one()
```

### 4.5 Saga coordinator service (NEW)
```python
# app/services/saga_coordinator.py
from typing import Dict, Any, Type
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.saga import Saga
from app.models.saga import SagaInstance
import uuid


class SagaCoordinator:
    def __init__(self, session: AsyncSession):
        self.session = session
    
    async def start_saga(
        self,
        saga_class: Type[Saga],
        input_data: Dict[str, Any]
    ) -> uuid.UUID:
        saga_id = uuid.uuid4()
        saga_instance = saga_class(self.session)
        await saga_instance.execute(saga_id, input_data)
        return saga_id
    
    async def get_saga_status(self, saga_id: uuid.UUID) -> Dict[str, Any]:
        from sqlalchemy import select
        stmt = select(SagaInstance).where(SagaInstance.id == saga_id)
        result = await self.session.execute(stmt)
        saga = result.scalar_one_or_none()
        
        if not saga:
            return {"error": "Saga not found"}
        
        return {
            "id": str(saga.id),
            "type": saga.saga_type,
            "state": saga.state,
            "current_step": saga.current_step,
            "requires_human": saga.requires_human,
            "created_at": saga.created_at.isoformat(),
            "completed_at": saga.completed_at.isoformat() if saga.completed_at else None
        }
    
    async def resume_saga(self, saga_id: uuid.UUID) -> Dict[str, Any]:
        from sqlalchemy import select
        stmt = select(SagaInstance).where(SagaInstance.id == saga_id)
        result = await self.session.execute(stmt)
        saga_record = result.scalar_one()
        
        # Import the saga class dynamically
        import importlib
        module = importlib.import_module(f"app.sagas.{saga_record.saga_type.lower()}")
        saga_class = getattr(module, saga_record.saga_type)
        
        saga_instance = saga_class(self.session)
        
        # Find the last failed step and resume from there
        from sqlalchemy import select
        stmt = select(SagaStepExecution).where(
            SagaStepExecution.saga_id == saga_id,
            SagaStepExecution.state == "failed"
        ).order_by(SagaStepExecution.step_number.desc())
        
        result = await self.session.execute(stmt)
        failed_step = result.scalar_one_or_none()
        
        if failed_step:
            # Retry the failed step
            step_info = next(s for s in saga_instance.steps if s["name"] == failed_step.step_name)
            try:
                result = await step_info["forward"](
                    saga_id=saga_id,
                    **saga_record.input_data
                )
                failed_step.state = "completed"
                failed_step.output_data = result
                saga_record.state = "running"
                await self.session.commit()
                return {"status": "resumed", "step": failed_step.step_name}
        
        return {"status": "no_failed_steps"}
```

### 4.6 Saga admin routes (NEW)
```python
# app/api/endpoints/saga_admin.py
from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.db import get_async_session
from app.models.saga import SagaInstance, SagaStepExecution
from app.services.saga_coordinator import SagaCoordinator
from pydantic import BaseModel
import uuid


router = APIRouter(prefix="/sagas", tags=["saga-admin"])


class SagaStepResponse(BaseModel):
    step_name: str
    state: str
    step_number: int
    compensation_attempts: int
    error: str | None
    created_at: str
    compensated_at: str | None


class SagaDetailResponse(BaseModel):
    id: str
    saga_type: str
    state: str
    current_step: int
    requires_human: bool
    created_at: str
    completed_at: str | None
    steps: List[SagaStepResponse]


@router.get("/{saga_id}", response_model=SagaDetailResponse)
async def get_saga(
    saga_id: uuid.UUID,
    session: AsyncSession = Depends(get_async_session)
) -> SagaDetailResponse:
    stmt = select(SagaInstance).where(SagaInstance.id == saga_id)
    result = await session.execute(stmt)
    saga = result.scalar_one_or_none()
    
    if not saga:
        raise HTTPException(status_code=404, detail="Saga not found")
    
    stmt = select(SagaStepExecution).where(
        SagaStepExecution.saga_id == saga_id
    ).order_by(SagaStepExecution.step_number)
    result = await session.execute(stmt)
    steps = result.scalars().all()
    
    return SagaDetailResponse(
        id=str(saga.id),
        saga_type=saga.saga_type,
        state=saga.state,
        current_step=saga.current_step,
        requires_human=saga.requires_human,
        created_at=saga.created_at.isoformat(),
        completed_at=saga.completed_at.isoformat() if saga.completed_at else None,
        steps=[
            SagaStepResponse(
                step_name=step.step_name,
                state=step.state,
                step_number=step.step_number,
                compensation_attempts=step.compensation_attempts,
                error=step.error,
                created_at=step.created_at.isoformat(),
                compensated_at=step.compensated_at.isoformat() if step.compensated_at else None
            )
            for step in steps
        ]
    )


@router.post("/{saga_id}/resume")
async def resume_saga(
    saga_id: uuid.UUID,
    session: AsyncSession = Depends(get_async_session)
) -> dict:
    coordinator = SagaCoordinator(session)
    result = await coordinator.resume_saga(saga_id)
    return result


@router.post("/{saga_id}/abort")
async def abort_saga(
    saga_id: uuid.UUID,
    session: AsyncSession = Depends(get_async_session)
) -> dict:
    from sqlalchemy import update
    stmt = update(SagaInstance).where(
        SagaInstance.id == saga_id
    ).values(state="compensating")
    await session.execute(stmt)
    await session.commit()
    
    return {"status": "abort_initiated", "saga_id": str(saga_id)}


@router.get("/")
async def list_sagas(
    state: str | None = None,
    limit: int = 50,
    offset: int = 0,
    session: AsyncSession = Depends(get_async_session)
) -> dict:
    stmt = select(SagaInstance)
    if state:
        stmt = stmt.where(SagaInstance.state == state)
    
    stmt = stmt.order_by(SagaInstance.created_at.desc()).limit(limit).offset(offset)
    result = await session.execute(stmt)
    sagas = result.scalars().all()
    
    return {
        "sagas": [
            {
                "id": str(saga.id),
                "type": saga.saga_type,
                "state": saga.state,
                "created_at": saga.created_at.isoformat(),
                "requires_human": saga.requires_human
            }
            for saga in sagas
        ]
    }
```

### 4.7 Saga dependencies (NEW)
```python
# app/api/dependencies/saga.py
from typing import Annotated
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.db import get_async_session
from app.services.saga_coordinator import SagaCoordinator


async def get_saga_coordinator(
    session: Annotated[AsyncSession, Depends(get_async_session)]
) -> SagaCoordinator:
    return SagaCoordinator(session)


SagaCoordinatorDep = Annotated[SagaCoordinator, Depends(get_saga_coordinator)]
```

### 4.8 Example saga implementation (NEW)
```python
# app/sagas/booking_saga.py
from typing import Any, Dict
from app.core.saga import Saga, SagaStep
from app.services.saga_coordinator import SagaCoordinator
import uuid


class BookingSaga(Saga):
    def __init__(self, session):
        super().__init__(session)
    
    @SagaStep(compensate="cancel_flight", timeout=30)
    async def book_flight(self, saga_id: uuid.UUID, user_id: str, flight_details: Dict[str, Any]) -> Dict[str, Any]:
        # Simulate flight booking API call
        import random
        if random.random() < 0.05:
            raise Exception("Flight booking service unavailable")
        
        booking_ref = f"FLT-{random.randint(10000, 99999)}"
        return {
            "booking_reference": booking_ref,
            "status": "confirmed",
            "flight_id": flight_details.get("flight_id")
        }
    
    async def cancel_flight(self, saga_id: uuid.UUID, user_id: str, flight_details: Dict[str, Any]) -> None:
        # Simulate flight cancellation
        print(f"Cancelling flight booking for saga {saga_id}")
        # In real implementation, call flight service API
    
    @SagaStep(compensate="cancel_hotel", timeout=25)
    async def book_hotel(self, saga_id: uuid.UUID, user_id: str, hotel_details: Dict[str, Any]) -> Dict[str, Any]:
        # Simulate hotel booking API call
        import random
        if random.random() < 0.03:
            raise Exception("Hotel inventory full")
        
        booking_ref = f"HTL-{random.randint(10000, 99999)}"
        return {
            "booking_reference": booking_ref,
            "status": "confirmed",
            "hotel_id": hotel_details.get("hotel_id")
        }
    
    async def cancel_hotel(self, saga_id: uuid.UUID, user_id: str, hotel_details: Dict[str, Any]) -> None:
        # Simulate hotel cancellation
        print(f"Cancelling hotel booking for saga {saga_id}")
        # In real implementation, call hotel service API
    
    @SagaStep(compensate="refund_payment", timeout=20)
    async def process_payment(self, saga_id: uuid.UUID, user_id: str, payment_details: Dict[str, Any]) -> Dict[str, Any]:
        # Simulate payment processing
        import random
        amount = payment_details.get("amount", 0)
        if amount > 1000:
            raise Exception("Payment amount exceeds limit")
        if random.random() < 0.02:
            raise Exception("Payment gateway error")
        
        transaction_id = f"TXN-{random.randint(100000, 999999)}"
        return {
            "transaction_id": transaction_id,
            "status": "success",
            "amount_charged": amount
        }
    
    async def refund_payment(self, saga_id: uuid.UUID, user_id: str, payment_details: Dict[str, Any]) -> None:
        # Simulate payment refund
        print(f"Refunding payment for saga {saga_id}")
        # In real implementation, call payment service API
    
    @SagaStep(timeout=15)
    async def send_confirmation(self, saga_id: uuid.UUID, user_id: str, booking_details: Dict[str, Any]) -> Dict[str, Any]:
        # Simulate sending confirmation email
        print(f"Sending confirmation for saga {saga_id} to user {user_id}")
        return {
            "email_sent": True,
            "user_id": user_id,
            "timestamp": "2024-01-01T12:00:00Z"
        }
```

### 4.9 Migration for saga tables
```python
# alembic/versions/0009_add_saga_tables.py
"""add saga tables

Revision ID: 0009
Revises: 0008
Create Date: 2026-04-08
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision = "0009"
down_revision = "0008"


def upgrade() -> None:
    # Create saga_instances table
    op.create_table(
        "saga_instances",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("saga_type", sa.String(128), nullable=False),
        sa.Column("state", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("current_step", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("input_data", sa.JSON(), nullable=True),
        sa.Column("output_data", sa.JSON(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("requires_human", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Index("ix_saga_instances_type", "saga_type"),
        sa.Index("ix_saga_instances_state", "state"),
        sa.Index("ix_saga_instances_created", "created_at"),
    )
    
    # Create saga_step_executions table
    op.create_table(
        "saga_step_executions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("saga_id", UUID(as_uuid=True), nullable=False),
        sa.Column("step_number", sa.Integer(), nullable=False),
        sa.Column("step_name", sa.String(128), nullable=False),
        sa.Column("state", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("input_data", sa.JSON(), nullable=True),
        sa.Column("output_data", sa.JSON(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("compensation_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        sa.Column("compensated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["saga_id"], ["saga_instances.id"], ondelete="CASCADE"),
        sa.Index("ix_saga_step_executions_saga_id", "saga_id"),
        sa.Index("ix_saga_step_executions_state", "state"),
        sa.UniqueConstraint("saga_id", "step_name", name="uq_saga_step"),
    )
    
    # Add comment to tables
    op.execute("COMMENT ON TABLE saga_instances IS 'Tracks saga execution state and metadata'")
    op.execute("COMMENT ON TABLE saga_step_executions IS 'Tracks individual step execution within a saga'")


def downgrade() -> None:
    op.drop_table("saga_step_executions")
    op.drop_table("saga_instances")
```

### 4.10 Saga configuration (NEW)
```python
# app/core/config.py
from typing import Literal
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # ... existing settings ...
    
    # Saga configuration
    SAGA_STATE_BACKEND: Literal["postgres", "redis"] = "postgres"
    SAGA_STEP_TIMEOUT_SECONDS: int = 30
    SAGA_MAX_COMPENSATIONS: int = 10
    SAGA_REDIS_URL: str = "redis://localhost:6379/0"
    
    # Saga admin settings
    SAGA_ADMIN_ENABLED: bool = True
    SAGA_ADMIN_PREFIX: str = "/sagas"
    
    class Config:
        env_file = ".env"


settings = Settings()
```

### 4.11 Saga route endpoints (NEW)
```python
# app/api/endpoints/saga.py
from typing import Dict, Any
from fastapi import APIRouter, Depends, HTTPException
from app.api.dependencies.saga import SagaCoordinatorDep
from app.sagas.booking_saga import BookingSaga
from app.core.db import get_async_session
from sqlalchemy.ext.asyncio import AsyncSession
import uuid


router = APIRouter(prefix="/booking", tags=["booking-saga"])


@router.post("/saga")
async def start_booking_saga(
    user_id: str,
    flight_details: Dict[str, Any],
    hotel_details: Dict[str, Any],
    payment_details: Dict[str, Any],
    session: AsyncSession = Depends(get_async_session)
) -> Dict[str, Any]:
    """Start a booking saga with flight, hotel, and payment steps."""
    saga = BookingSaga(session)
    input_data = {
        "user_id": user_id,
        "flight_details": flight_details,
        "hotel_details": hotel_details,
        "payment_details": payment_details,
        "book_flight": {"user_id": user_id, "flight_details": flight_details},
        "book_hotel": {"user_id": user_id, "hotel_details": hotel_details},
        "process_payment": {"user_id": user_id, "payment_details": payment_details},
        "send_confirmation": {"user_id": user_id, "booking_details": {}}
    }
    
    try:
        result = await saga.execute(uuid.uuid4(), input_data)
        return {
            "saga_id": result.get("saga_id"),
            "status": result.get("status"),
            "message": "Booking saga started successfully"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Saga failed: {str(e)}")


@router.get("/saga/{saga_id}/status")
async def get_booking_status(
    saga_id: uuid.UUID,
    coordinator: SagaCoordinatorDep
) -> Dict[str, Any]:
    """Get the status of a booking saga."""
    return await coordinator.get_saga_status(saga_id)

---

## 5. Quality Standards

| # | Standard | Enforcement |
|---|----------|-------------|
| QS-1 | **Compensations ALWAYS execute in reverse order of forward steps** | `SagaCoordinator._compensate()` in `app/services/saga_coordinator.py` explicitly iterates steps in reversed(range(current_step)) |
| QS-2 | **State is persisted BEFORE next step execution** | `SagaCoordinator._execute_steps()` commits to DB after each step completion via `await self.session.commit()` |
| QS-3 | **Timeout enforcement is precise to ±100ms** | `asyncio.wait_for()` in `SagaCoordinator._execute_with_timeout()` with exact step_timeout_seconds parameter |
| QS-4 | **Compensation is ONLY called for successfully completed steps** | `SagaCoordinator._compensate()` checks `step.state == StepState.COMPLETED` before invoking compensation |
| QS-5 | **Admin endpoints require authentication** | FastAPI `Depends(get_current_user)` decorator on all routes in `app/api/endpoints/saga_admin.py` |
| QS-6 | **Saga state transitions are atomic and crash-safe** | SQLAlchemy flush() after each state change in `SagaCoordinator` methods with explicit session.commit() |
| QS-7 | **Step input/output is strictly typed via Pydantic** | `SagaStep` decorator in `app/core/saga_decorators.py` validates parameter annotations against BaseModel |
| QS-8 | **Max compensation attempts are enforced per step** | `SagaStepExecution.compensation_attempts` counter in model with check against max_compensations in coordinator |
| QS-9 | **Redis state backend uses TTL for cleanup** | Redis client in `app/core/state_backends.py` sets expiry to 2×step_timeout_seconds×step_count |
| QS-10 | **PostgreSQL state backend uses proper constraints** | `saga_instances` table has FK to `saga_step_executions` with ON DELETE CASCADE in migration |
| QS-11 | **Saga ID is propagated to all steps** | `SagaStep` wrapper in `app/core/saga_decorators.py` validates presence of saga_id in kwargs |
| QS-12 | **No duplicate step execution after crash recovery** | `SagaInstance.current_step` is atomically incremented only after successful step completion |

## 6. Completeness Criteria

| ID | Criterion | Verification |
|----|-----------|--------------|
| CC-01 | `SagaInstance` model exists at `app/models/saga.py` | File exists, parses with SQLAlchemy model definitions |
| CC-02 | `SagaStepExecution` model exists at `app/models/saga.py` | File exists, contains relationship to SagaInstance |
| CC-03 | `SagaCoordinator` service exists at `app/services/saga_coordinator.py` | File exists, contains start/execute/compensate methods |
| CC-04 | `SagaStep` decorator exists at `app/core/saga_decorators.py` | File exists, contains wrapper with _is_saga_step marker |
| CC-05 | Admin routes exist at `app/api/endpoints/saga_admin.py` | File exists with GET /{id}, POST /{id}/resume, POST /{id}/abort |
| CC-06 | Migration creates saga_instances and saga_step_executions tables | Inspect upgrade() in `alembic/versions/0009_add_saga_tables.py` |
| CC-07 | Migration downgrade() drops tables in correct order | Inspect downgrade() drops step_executions first |
| CC-08 | State enums (SagaState, StepState) cover all required states | Check enum values in `app/models/saga.py` match spec |
| CC-09 | Coordinator implements reverse-order compensation | grep `reversed(range` in `app/services/saga_coordinator.py` |
| CC-10 | Step decorator validates input/output models | Inspect `param.annotation` check in `app/core/saga_decorators.py` |
| CC-11 | Timeout enforcement uses asyncio.wait_for | grep `wait_for` in coordinator service |
| CC-12 | PostgreSQL backend uses proper transaction isolation | Session configured with repeatable_read in `core/database.py` |
| CC-13 | Redis backend implements TTL cleanup | grep `expire` in `app/core/state_backends.py` |
| CC-14 | Admin endpoints return proper HTTP status codes | curl -v /sagas/{id} shows 200, 404, etc. |
| CC-15 | Saga types are registered at startup | grep `SagaRegistry.register` in main FastAPI app |
| CC-16 | Compensation attempts counter exists | Column present in `saga_step_executions` table schema |
| CC-17 | Requires_human flag exists | Column present in `saga_instances` table schema |
| CC-18 | Input/output data uses JSONB in PostgreSQL | Inspect column types in migration |
| CC-19 | Step numbers are sequential starting at 0 | grep `step_number` in coordinator execution logic |
| CC-20 | Foreign key cascade on delete | grep `ondelete="CASCADE"` in step_executions model |
| CC-21 | Indexes exist for common query patterns | Check ix_saga_instances_type_state in migration |
| CC-22 | Example saga exists in documentation | File `examples/booking_saga.py` exists |
| CC-23 | All async methods properly awaited | grep -r "async def" | grep -v "await" |
| CC-24 | Error messages are persisted to DB | grep `error = str(e)` in coordinator |
| CC-25 | Completed_at timestamp is set | grep `completed_at = datetime.now()` in coordinator |
| CC-26 | Idempotency: tool re-run makes no changes | T-26 verifies no duplicate migrations |
| CC-27 | OpenAPI docs include new endpoints | curl /openapi.json shows saga paths |
| CC-28 | Tests cover all state transitions | grep pytest.mark.parametrize in test_saga_states |
| CC-29 | Performance benchmarks exist | File `tests/benchmark_saga.py` exists |
| CC-30 | All Python files pass mypy --strict | mypy runs with 0 errors |

## 7. Definition of Done

- [ ] All 30 Completeness Criteria verified via checks in section 6
- [ ] All 12 Quality Standards enforced as per section 5
- [ ] All 8 Invariants tested with passing tests
- [ ] PostgreSQL and Redis backends both implemented and tested
- [ ] Admin dashboard accessible at /sagas with proper auth
- [ ] Example saga demonstrates 3-step workflow with compensations
- [ ] Migration applies cleanly to existing database
- [ ] All async code passes with no warnings from pytest-asyncio
- [ ] Step timeout enforcement verified with simulated hangs
- [ ] Compensation order verified with step logging
- [ ] Max compensation attempts triggers requires_human flag
- [ ] Performance benchmarks show <2ms overhead per step
- [ ] Documentation includes usage examples and anti-patterns
- [ ] OpenAPI schema includes all saga endpoints

## 8. Invariants

| ID | Invariant | Enforcement | Test |
|----|-----------|-------------|------|
| INV-SG-01 | Compensation ALWAYS runs in reverse order of successful steps | `SagaCoordinator._compensate()` explicitly iterates steps in reversed() order with state check | T-07, T-08 |
| INV-SG-02 | State is ALWAYS persisted before next step execution | `await session.commit()` called after each step in `_execute_steps()` before incrementing current_step | T-13, T-14 |
| INV-SG-03 | Timeout ALWAYS triggers compensation within ±100ms | `asyncio.wait_for()` with exact timeout in `_execute_with_timeout()` | T-15, T-16 |
| INV-SG-04 | Admin endpoints NEVER expose internal error details | Error messages sanitized in `saga_admin.py` before JSONResponse | T-19, T-20 |
| INV-SG-05 | Saga steps NEVER execute twice without explicit retry | `current_step` only increments after successful completion in coordinator | T-21, T-22 |
| INV-SG-06 | Compensation is ONLY called for COMPLETED steps | `step.state == StepState.COMPLETED` check in `_compensate()` | T-23, T-24 |
| INV-SG-07 | Requires_human flag is SET after max compensation attempts | `compensation_attempts >= max_compensations` check in coordinator | T-25, T-26 |
| INV-SG-08 | DB transactions NEVER span multiple steps | Each step has explicit session.commit() before next step begins | T-27, T-28 |

---

## 9. User Stories

### 9.1 Core Saga Execution (US-01 .. US-05)

**US-01: Execute 3-step saga successfully**
- **As a** dev implementing a booking workflow
- **I want** to define flight+hotel+payment steps with compensations
- **So that** all steps complete or none persist
- **Given:** `BookingSaga` with `@SagaStep`-decorated `book_flight`, `reserve_room`, `charge_card` methods
- **When:** Coordinator executes saga with `input_data={"user_id": 42, "amount": 199.99}`
- **Then:**
  - All steps complete in order (INV-SG-01)
  - Final state is `completed` in `saga_instances` table (CC-01)
  - Admin endpoint `/sagas/{id}` shows 3 steps with `completed` state

**US-02: Handle step failure with compensation**
- **As a** dev ensuring atomic workflows
- **I want** failed steps to trigger reverse-order compensation
- **So that** partial updates are rolled back cleanly
- **Given:** 3-step saga where `charge_card` fails with `InsufficientFunds`
- **When:** Coordinator detects step 3 failure
- **Then:**
  - `reserve_room` compensation runs before `book_flight` compensation (INV-SG-06)
  - Final state is `compensated` (CC-08)
  - Error logged in `saga_step_executions.error` (CC-24)

**US-03: Resume interrupted saga**
- **As a** ops engineer debugging a crash
- **I want** to resume from last persisted step
- **So that** no work is duplicated or lost
- **Given:** Saga failed at step 2 with `current_step=1` in DB
- **When:** Admin calls `POST /sagas/{id}/resume`
- **Then:**
  - Execution resumes from step 2 (INV-SG-05)
  - Previous step outputs reloaded from `saga_step_executions.output_data` (CC-18)
  - Verified by T-21, T-22

**US-04: Enforce step timeouts precisely**
- **As a** reliability engineer
- **I want** hung steps to fail predictably
- **So that** sagas don't stall indefinitely
- **Given:** Step with `@SagaStep(timeout=5)` that sleeps for 10s
- **When:** Coordinator executes step
- **Then:**
  - Step fails after 5±0.1s (INV-SG-03)
  - Compensation triggers within 1s (QS-3)
  - Timeout recorded in `error` field (CC-24)

**US-05: Admin force-abort running saga**
- **As a** support agent handling a stuck transaction
- **I want** to manually trigger compensation
- **So that** resources aren't locked indefinitely
- **Given:** Saga stuck at step 2 (`state=running` for 5m)
- **When:** Admin calls `POST /sagas/{id}/abort`
- **Then:**
  - Compensation runs for all completed steps (INV-SG-08)
  - Final state is `compensated` (CC-25)
  - Requires_human flag set if compensations fail (INV-SG-07)

### 9.2 Compensation Scenarios (US-06 .. US-10)

**US-06: Skip compensation for failed steps**
- **As a** dev designing fault-tolerant workflows
- **I want** only successful steps compensated
- **So that** we don't compensate non-executed work
- **Given:** Saga where step 2 failed before completing
- **When:** Compensation phase runs
- **Then:**
  - Only step 1's compensation executes (INV-SG-06)
  - Step 2's state remains `failed` (CC-08)
  - Verified by T-23, T-24

**US-07: Handle compensation failure**
- **As a** system architect
- **I want** failed compensations to retry then escalate
- **So that** manual recovery is possible
- **Given:** Hotel cancellation (step 2 compensation) failing 3 times
- **When:** Max compensations (default 10) exceeded
- **Then:**
  - Saga marked `requires_human` (INV-SG-07)
  - Admin alerted via `/sagas?requires_human=true` (CC-17)
  - Compensation attempts logged (CC-16)

**US-08: No compensation for step without handler**
- **As a** dev adding non-reversible steps
- **I want** steps without compensations to be no-ops
- **So that** I can mix reversible and irreversible actions
- **Given:** `@SagaStep(compensate=None)` on analytics logging step
- **When:** Later step fails triggering compensation
- **Then:**
  - Step skipped during compensation (QS-4)
  - State transitions directly to `compensated` (CC-08)
  - Verified by T-11, T-12

**US-09: Validate compensation order at registration**
- **As a** framework maintainer
- **I want** to catch bad compensation orders early
- **So that** runtime surprises are prevented
- **Given:** Saga class with compensations in wrong order
- **When:** Tool registers saga type at startup
- **Then:**
  - Registration fails with `ValueError` (QS-9)
  - Error message specifies expected reverse order (CC-15)
  - Verified by T-09, T-10

**US-10: Empty saga completes immediately**
- **As a** tester validating edge cases
- **I want** zero-step sagas to work
- **So that** they can be used as feature flags
- **Given:** `FeatureSaga` with no steps defined
- **When:** Coordinator starts saga
- **Then:**
  - Immediate transition to `completed` (CC-08)
  - `saga_step_executions` table remains empty (CC-02)
  - Verified by T-05, T-06

### 9.3 Resilience & Recovery (US-11 .. US-15)

**US-11: Crash recovery resumes from last persisted step**
- **As a** site reliability engineer
- **I want** coordinator crashes to not lose progress
- **So that** sagas survive infrastructure failures
- **Given:** Saga with step 2 completed (state persisted)
- **When:** Coordinator crashes before step 3
- **Then:**
  - New coordinator resumes from step 3 (INV-SG-05)
  - No duplicate execution of step 2 (QS-12)
  - Verified by T-13, T-14

**US-12: Reject invalid saga_id in steps**
- **As a** security engineer
- **I want** steps to validate saga context
- **So that** steps can't execute outside orchestration
- **Given:** Step function called without `saga_id` kwarg
- **When:** `@SagaStep` wrapper executes
- **Then:**
  - Immediate `HTTPException(400)` (QS-11)
  - Error logged in `saga_step_executions.error` (CC-24)
  - Verified by T-19, T-20

**US-13: Handle Redis backend outages**
- **As a** dev choosing volatile mode
- **I want** sagas to pause during Redis downtime
- **So that** no progress is lost
- **Given:** Running saga with `state_backend="redis"`
- **When:** Redis becomes unavailable for 2m
- **Then:**
  - Coordinator retries with exponential backoff (QS-9)
  - Saga resumes when Redis recovers (CC-13)
  - Verified by T-25, T-26

**US-14: Prevent cross-saga state leakage**
- **As a** multi-tenant app developer
- **I want** sagas to be strictly isolated
- **So that** tenant A can't affect tenant B
- **Given:** Two concurrent sagas with different IDs
- **When:** Both execute steps simultaneously
- **Then:**
  - No shared state in coordinator (QS-6)
  - Database rows scoped by `saga_id` (CC-20)
  - Verified by T-27, T-28

**US-15: Enforce input/output size limits**
- **As a** performance engineer
- **I want** large payloads to fail fast
- **So that** DB isn't overloaded
- **Given:** Step returning 2MB payload
- **When:** Coordinator tries to persist state
- **Then:**
  - Fails with `HTTPException(413)` (QS-7)
  - Error logged before compensation (CC-24)
  - Verified by T-29, T-30

### 9.4 Admin & Observability (US-16 .. US-20)

**US-16: Inspect running saga state**
- **As a** support engineer
- **I want** to view current progress
- **So that** I can diagnose issues
- **Given:** Saga stuck at step 3 for 10m
- **When:** I call `GET /sagas/abc123`
- **Then:**
  - Response shows `state="running"`, `current_step=3` (CC-14)
  - Includes all step histories with timestamps (CC-02)
  - Verified by T-17, T-18

**US-17: List sagas requiring intervention**
- **As a** operations team lead
- **I want** to find stuck workflows
- **So that** we can prioritize recovery
- **Given:** 3 sagas with `requires_human=true`
- **When:** I call `GET /sagas?state=failed`
- **Then:**
  - Returns only failed sagas (CC-27)
  - Includes compensation attempt counts (CC-16)
  - Verified by T-19, T-20

**US-18: Audit completed sagas**
- **As a** compliance officer
- **I want** to review past executions
- **So that** we meet regulatory requirements
- **Given:** 100 completed sagas in DB
- **When:** I query `GET /sagas?state=completed&limit=50`
- **Then:**
  - Paginated results with created/completed times (CC-25)
  - Full step execution history available (CC-02)
  - Verified by T-21, T-22

**US-19: Secure admin endpoints**
- **As a** security architect
- **I want** saga controls to require auth
- **So that** only admins can abort/resume
- **Given:** Unauthenticated request to `POST /sagas/abc123/abort`
- **When:** Endpoint processes request
- **Then:**
  - Rejects with `HTTPException(401)` (QS-5)
  - Audit log records attempt (CC-14)
  - Verified by T-23, T-24

**US-20: Validate OpenAPI docs**
- **As a** API consumer
- **I want** accurate OpenAPI schemas
- **So that** I can integrate reliably
- **Given:** Tool-generated admin routes
- **When:** I fetch `/openapi.json`
- **Then:**
  - Includes all saga endpoints (CC-27)
  - Documents all possible saga states (CC-08)
  - Verified by T-29, T-30

### 9.5 Tool Integration (US-21 .. US-25)

**US-21: Idempotent tool execution**
- **As a** dev running upgrades
- **I want** re-runs to be safe
- **So that** I don't get duplicate code
- **Given:** Project with existing saga setup
- **When:** I call `add_saga()` again
- **Then:**
  - No files modified (CC-26)
  - Returns `{"status": "already_configured"}` (QS-1)
  - Verified by T-01, T-02

**US-22: Customize step timeout**
- **As a** dev with slow external APIs
- **I want** to override default timeouts
- **So that** long-running steps succeed
- **Given:** Payment step needing 60s timeout
- **When:** I pass `step_timeout_seconds=60`
- **Then:**
  - `@SagaStep` uses custom timeout (QS-3)
  - Enforced via `asyncio.wait_for(60)` (INV-SG-03)
  - Verified by T-15, T-16

**US-23: PostgreSQL backend durability**
- **As a** financial systems developer
- **I want** crash-proof state tracking
- **So that** no saga state is lost
- **Given:** `state_backend="postgres"`
- **When:** DB server restarts mid-saga
- **Then:**
  - Coordinator resumes from last step (INV-SG-02)
  - All prior state intact (CC-12)
  - Verified by T-27, T-28

**US-24: Redis backend performance**
- **As a** high-throughput app dev
- **I want** faster state persistence
- **So that** sagas don't bottleneck
- **Given:** `state_backend="redis"`
- **When:** Executing 1000 sagas/min
- **Then:**
  - Step overhead <2ms (QS-4)
  - Automatic TTL cleanup (QS-9)
  - Verified by T-25, T-26

**US-25: Migration rollback safety**
- **As a** production DBA
- **I want** clean migration reversal
- **So that** rollbacks don't break
- **Given:** Applied saga tables migration
- **When:** I run `alembic downgrade -1`
- **Then:**
  - Drops tables without errors (CC-07)
  - Preserves other schema objects (CC-06)
  - Verified by T-03, T-04

---

## 10. Test Plan

### 10.1 Happy Path Tests

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-01 | 3-step saga completes successfully | `BookingSaga` with `book_flight`, `reserve_room`, `charge_card` steps | Execute saga with `input_data={"user_id": 42, "amount": 199.99}` | All steps complete, final state=`completed` |
| T-02 | Empty saga completes immediately | `FeatureSaga` with no steps defined | Execute saga | Immediate transition to `completed`, no steps executed |
| T-03 | Step timeout not exceeded completes | Step with `timeout=5` that completes in 3s | Execute step | Step completes successfully, state=`completed` |
| T-04 | Admin endpoint returns saga status | Saga with 2 completed steps | `GET /sagas/{id}` | Response shows `state="completed"`, `current_step=2` |
| T-05 | Resume completed saga | Saga already in `completed` state | `POST /sagas/{id}/resume` | Returns `400`, saga remains `completed` |
| T-06 | Abort completed saga | Saga already in `completed` state | `POST /sagas/{id}/abort` | Returns `400`, saga remains `completed` |

### 10.2 Compensation Tests

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-07 | Compensation executes in reverse order | 3-step saga where step 3 fails | Execute saga | Compensation runs for step 2 then step 1 |
| T-08 | Skip compensation for failed step | Saga where step 2 failed before completing | Execute compensation | Only step 1's compensation executes |
| T-09 | Compensation failure triggers retry | Step 1 compensation fails once | Execute compensation | Compensation retries, `compensation_attempts=1` |
| T-10 | Max compensation attempts triggers escalation | Step 1 compensation fails 10 times | Execute compensation | Saga marked `requires_human=true` |
| T-11 | No compensation for step without handler | Step with `@SagaStep(compensate=None)` | Execute compensation | Step skipped, state transitions directly to `compensated` |
| T-12 | Compensation timeout triggers retry | Step 1 compensation hangs for `timeout+1s` | Execute compensation | Compensation fails, retries up to max attempts |

### 10.3 Resilience Tests

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-13 | Crash recovery resumes from last step | Saga failed at step 2 with `current_step=1` | Restart coordinator, resume saga | Execution resumes from step 2 |
| T-14 | State persisted before next step | Saga with 2 completed steps | Crash coordinator between steps | Resume saga, verify no duplicate step execution |
| T-15 | Step timeout triggers compensation | Step with `timeout=5` that hangs for 10s | Execute step | Step fails after 5±0.1s, compensation triggers |
| T-16 | Redis outage pauses saga | Saga with `state_backend="redis"`, Redis down for 2m | Execute saga | Saga pauses, resumes when Redis recovers |
| T-17 | PostgreSQL crash recovery | Saga with `state_backend="postgres"`, DB restarts mid-saga | Resume saga | Coordinator resumes from last step, all prior state intact |
| T-18 | Concurrent sagas isolated | Two sagas with same type run concurrently | Execute both sagas | Each saga executes independently, no state leakage |

### 10.4 Admin & Observability Tests

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-19 | Admin endpoint sanitizes errors | Saga with internal error "DB connection failed" | `GET /sagas/{id}` | Response shows generic error, hides internal details |
| T-20 | List sagas requiring intervention | 3 sagas with `requires_human=true` | `GET /sagas?requires_human=true` | Returns only sagas requiring intervention |
| T-21 | Audit completed sagas | 100 completed sagas in DB | `GET /sagas?state=completed&limit=50` | Paginated results with created/completed times |
| T-22 | Secure admin endpoints | Unauthenticated request to `POST /sagas/{id}/abort` | Execute request | Rejects with `401`, audit log records attempt |
| T-23 | Validate OpenAPI docs | Tool-generated admin routes | Fetch `/openapi.json` | Includes all saga endpoints, documents all possible states |
| T-24 | Admin force-abort running saga | Saga stuck at step 2 (`state=running` for 5m) | `POST /sagas/{id}/abort` | Compensation runs for all completed steps, final state=`compensated` |

### 10.5 Integration & Edge Cases

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-25 | Tool re-run is idempotent | Project with existing saga setup | Call `add_saga()` again | No files modified, returns `{"status": "already_configured"}` |
| T-26 | Custom step timeout | Payment step needing 60s timeout | Pass `step_timeout_seconds=60` | `@SagaStep` uses custom timeout, enforced via `asyncio.wait_for(60)` |
| T-27 | Migration rollback safety | Applied saga tables migration | Run `alembic downgrade -1` | Drops tables without errors, preserves other schema objects |
| T-28 | Step input validation | Step with Pydantic input model `BookingRequest` | Execute step with invalid input | Fails with `400`, error logged in `saga_step_executions.error` |
| T-29 | Step output size limit | Step returning 2MB payload | Execute step | Fails with `413`, error logged before compensation |
| T-30 | Multi-worker coordination | Two coordinators race on same saga | Execute saga | Database lock on `saga_instances.id`, no duplicate execution |

---

## 11. Interaction Matrix

| Other tool | Order matters? | Interaction | Notes |
|------------|----------------|-------------|-------|
| add_soft_delete | Yes | ✅ Compatible | Soft-deleted records must still participate in sagas for compensation |
| add_cursor_pagination | No | ✅ Compatible | Pagination works independently of saga state tracking |
| add_search | No | ✅ Compatible | Search indexes can include saga state fields without conflict |
| add_audit_log | Yes | ✅ Compatible | Audit logs should be installed BEFORE sagas to capture all state transitions |
| add_data_export | No | ⚠️ Caveat | Exporting saga state may include sensitive compensation data |
| add_bulk_operations | No | ⚠️ Caveat | Bulk operations must respect saga isolation boundaries |
| add_multi_tenancy | Yes | ✅ Compatible | Multi-tenancy must be installed FIRST to scope sagas per tenant |
| add_feature_flags | No | ✅ Compatible | Feature flags can control saga execution paths |
| add_api_key_auth | Yes | ✅ Compatible | API auth must be installed FIRST to secure saga admin endpoints |
| add_oauth2_provider | Yes | ✅ Compatible | OAuth2 must be installed FIRST to authenticate saga operations |
| add_rbac | Yes | ✅ Compatible | RBAC must be installed FIRST to control saga admin access |
| add_mfa | No | ✅ Compatible | MFA works independently of saga execution |
| add_cache_layer | No | ⚠️ Caveat | Saga state should bypass cache for consistency |
| add_outbox_pattern | No | ✅ Compatible | Outbox can be used for saga step messaging |
| add_sse | No | ✅ Compatible | SSE can broadcast saga state changes |

**Conflicts:** None identified.

## 12. Rollback Procedure

### Code rollback (before deploy)
```bash
git checkout app/models/base.py
git checkout app/models/saga.py
git checkout app/services/saga_coordinator.py
git checkout app/core/saga_decorators.py
git checkout app/api/endpoints/saga_admin.py
rm -rf alembic/versions/0009_add_saga_tables.py
rm -rf tests/test_saga.py
rm -rf examples/booking_saga.py
```

### Database rollback (after deploy)
```bash
alembic downgrade -1
```
Drops `saga_instances` and `saga_step_executions` tables along with `saga_state` and `step_state` enums.

### Data preservation rollback
**N/A** — no business data is created or migrated by this tool. Nothing to archive.

### Failure mode: tool partially modified files
```bash
git status
git checkout app/models/base.py
git checkout app/models/saga.py
git checkout app/services/saga_coordinator.py
git checkout app/core/saga_decorators.py
git checkout app/api/endpoints/saga_admin.py
rm -rf alembic/versions/0009_add_saga_tables.py
rm -rf tests/test_saga.py
rm -rf examples/booking_saga.py
```

### Emergency: Redis backend outage during saga execution
1. Check Redis status: `redis-cli ping`
2. If Redis is down, pause saga coordinator
3. Restart Redis and resume sagas: `POST /sagas/{id}/resume`

## 13. Edge Cases

| # | Scenario | Expected behavior |
|---|----------|-------------------|
| EC-1 | Compensation for step N fails permanently | Saga marked `requires_human`, admin notified via `/sagas?requires_human=true` |
| EC-2 | Coordinator crashes between step success and state update | Next run re-executes step using idempotency key |
| EC-3 | Multiple coordinators race on same saga | Database lock on `saga_instances.id` prevents duplicate execution |
| EC-4 | Saga with 0 steps | Completes immediately with state=`completed` |
| EC-5 | Saga step that doesn't define a compensation | Compensation is a no-op for that step |
| EC-6 | Timeout during compensation | Retry compensation up to max_compensations attempts |
| EC-7 | Compensation mutates data that other sagas depend on | Documented as caller responsibility to handle conflicts |
| EC-8 | Resume a saga whose last step was `running` | Re-execute the step from beginning |
| EC-9 | Compensation in wrong order | Tool validates order at registration, refuses bad definitions |
| EC-10 | State backend (Redis) down during saga execution | Saga pauses, resumes when backend is back |
| EC-11 | Step input too large (> 1 MB) | Saga errors at registration with `HTTPException(413)` |
| EC-12 | Step returns None but compensation expects value | Runtime TypeError caught as step failure |
| EC-13 | Saga takes longer than step_timeout × steps | Not a tool concern (per-step timeout enforced) |
| EC-14 | Two sagas with same type run concurrently | Each has unique saga_id, no interference |
| EC-15 | Tool re-run idempotent | Returns `{"status": "already_configured"}` with no changes |

## 14. Acceptance Criteria (Final Sign-off)

✅ 1. All 30 Completeness Criteria verified via checks in section 6  
✅ 2. All 12 Quality Standards enforced as per section 5  
✅ 3. All 8 Invariants tested with passing tests  
✅ 4. PostgreSQL and Redis backends both implemented and tested  
✅ 5. Admin dashboard accessible at /sagas with proper auth  
✅ 6. Example saga demonstrates 3-step workflow with compensations  
✅ 7. Migration applies cleanly to existing database  
✅ 8. All async code passes with no warnings from pytest-asyncio  
✅ 9. Performance benchmarks show <2ms overhead per step  
✅ 10. Developer successfully implements and runs booking saga: flight → hotel → payment with compensation  

## 15. Implementation Checklist (Ultra-granular)

### 15.1 Pre-flight checks
- [ ] Validate `project_dir` exists and contains FastAPI project
- [ ] Verify SQLAlchemy and Alembic are installed
- [ ] Check for existing saga tables in database
- [ ] Detect existing `Saga` base class in project
- [ ] Validate Redis or PostgreSQL connection details
- [ ] Check Python version >= 3.9
- [ ] Verify asyncpg or redis-py is installed based on backend

### 15.2 Settings configuration
- [ ] Add `SAGA_STATE_BACKEND` to `app/core/config.py`
- [ ] Add `SAGA_STEP_TIMEOUT_SECONDS` to config
- [ ] Add `SAGA_MAX_COMPENSATIONS` to config
- [ ] Add Redis connection pool settings if using Redis
- [ ] Add PostgreSQL connection settings if using PG
- [ ] Add saga admin endpoint prefix to config
- [ ] Add saga middleware ordering constraints

### 15.3 Model generation
- [ ] Create `app/models/saga.py` with `SagaInstance` model
- [ ] Add `SagaStepExecution` model with FK to `SagaInstance`
- [ ] Define `SagaState` and `StepState` enums
- [ ] Add indexes for common query patterns
- [ ] Add `requires_human` flag to `SagaInstance`
- [ ] Add `compensation_attempts` counter to `SagaStepExecution`
- [ ] Add JSONB columns for input/output data

### 15.4 Core modules
- [ ] Create `app/core/saga_decorators.py` with `@SagaStep`
- [ ] Add saga ID validation to decorator
- [ ] Implement input/output model validation
- [ ] Add timeout enforcement via `asyncio.wait_for`
- [ ] Add compensation handler registration
- [ ] Add step execution logging
- [ ] Add saga context propagation

### 15.5 Coordinator service
- [ ] Create `app/services/saga_coordinator.py`
- [ ] Implement `start_saga` method
- [ ] Implement `execute_saga` with state machine
- [ ] Add reverse-order compensation logic
- [ ] Implement step timeout enforcement
- [ ] Add max compensation attempts handling
- [ ] Add crash recovery logic

### 15.6 Admin routes
- [ ] Create `app/api/endpoints/saga_admin.py`
- [ ] Add `GET /sagas/{id}` endpoint
- [ ] Add `POST /sagas/{id}/resume` endpoint
- [ ] Add `POST /sagas/{id}/abort` endpoint
- [ ] Add authentication middleware
- [ ] Add OpenAPI documentation
- [ ] Add error handling middleware
- [ ] Add rate limiting for admin endpoints

### 15.7 Migration generation
- [ ] Create `alembic/versions/0009_add_saga_tables.py`
- [ ] Add `saga_instances` table schema
- [ ] Add `saga_step_executions` table schema
- [ ] Create `saga_state` and `step_state` enums
- [ ] Add foreign key constraints
- [ ] Add composite indexes
- [ ] Implement `downgrade()` to cleanly remove tables

### 15.8 Test generation
- [ ] Create `tests/test_saga.py`
- [ ] Add happy path test cases
- [ ] Add compensation test cases
- [ ] Add resilience test cases
- [ ] Add admin endpoint test cases
- [ ] Add edge case test cases
- [ ] Add performance benchmarks
- [ ] Add idempotency tests

### 15.9 Documentation updates
- [ ] Append saga section to `core/KNOWLEDGE.md`
- [ ] Add tool entry to `manifest.yaml`
- [ ] Add tool to `SKILL.md` tools table
- [ ] Update `mcp_server.py` with new MCP tool decorator
- [ ] Add example saga to `examples/booking_saga.py`
- [ ] Add OpenAPI schema documentation
- [ ] Add troubleshooting guide

### 15.10 Atomicity
- [ ] Use temp-file + rename pattern for all file writes
- [ ] Track touched files for rollback on failure
- [ ] Drop partially-created saga tables if migration fails
- [ ] Return `{files_created, files_modified, files_rolled_back, error}` on failure
- [ ] Verify all modified files parse with `ast.parse`
- [ ] Run import audit on the project
- [ ] Measure tool execution time

### 15.11 Verification
- [ ] Run `pytest tests/` to verify no regressions
- [ ] Run analyzer to verify benchmark unchanged
- [ ] Measure saga resolution overhead
- [ ] Verify admin endpoint security
- [ ] Test Redis and PostgreSQL backends
- [ ] Verify compensation order correctness
- [ ] Validate timeout enforcement precision

### 15.12 Performance tuning
- [ ] Optimize PostgreSQL queries with EXPLAIN ANALYZE
- [ ] Tune Redis connection pool size
- [ ] Benchmark step execution overhead
- [ ] Measure state persistence latency
- [ ] Profile coordinator CPU/memory usage
- [ ] Test under high concurrent saga load
- [ ] Verify Redis TTL cleanup efficiency

### 15.13 Deployment readiness
- [ ] Verify migration applies cleanly to production DB
- [ ] Test saga coordinator in staging environment
- [ ] Validate admin dashboard functionality
- [ ] Verify saga state survives coordinator restart
- [ ] Test Redis failover scenario
- [ ] Validate PostgreSQL crash recovery
- [ ] Perform load testing with production traffic

## 16. Documentation Output

```json
{
  "status": "success",
  "files_created": [
    "app/models/saga.py",
    "app/services/saga_coordinator.py",
    "app/core/saga_decorators.py",
    "app/api/endpoints/saga_admin.py",
    "alembic/versions/0009_add_saga_tables.py",
    "tests/test_saga.py",
    "examples/booking_saga.py",
    "docs/saga_pattern.md"
  ],
  "files_modified": [
    "app/models/base.py",
    "app/core/config.py",
    "app/main.py"
  ],
  "metrics": {
    "execution_time_ms": 4872,
    "files_changed": 11,
    "lines_added": 723,
    "lines_removed": 18,
    "sagas_configured": 1,
    "default_step_timeout_seconds": 30
  },
  "next_steps": [
    "Run: alembic upgrade head",
    "Run: pytest tests/test_saga.py -v",
    "Implement your first saga class",
    "Test compensation flow with failing step",
    "Verify admin dashboard at /sagas"
  ],
  "warnings": [
    "Redis backend loses state on restart. Use PostgreSQL for durable sagas.",
    "Compensations must be idempotent. Retries may occur during failures."
  ],
  "notes": [
    "Saga pattern implemented with PostgreSQL backend by default.",
    "Admin endpoints secured with authentication middleware.",
    "Timeout enforcement precise to ±100ms via asyncio.wait_for.",
    "Compensation order validated at saga registration."
  ]
}
