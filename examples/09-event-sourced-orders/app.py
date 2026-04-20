"""Event-sourced orders — append-only log + outbox + idempotent consumer."""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from itertools import count
from typing import Callable, Literal


EventType = Literal["OrderPlaced", "PaymentAuthorized", "Shipped",
                    "Delivered", "Returned"]


@dataclass(frozen=True)
class OrderEvent:
    offset: int
    event_id: str
    order_id: str
    type: EventType
    payload: dict


@dataclass
class OrderState:
    order_id: str
    status: str = "pending"
    paid: bool = False
    shipped: bool = False
    delivered: bool = False
    returned: bool = False


def fold(events: list[OrderEvent]) -> dict[str, OrderState]:
    """Pure fold — identical input produces identical output on any node."""
    out: dict[str, OrderState] = {}
    for e in events:
        s = out.setdefault(e.order_id, OrderState(order_id=e.order_id))
        if e.type == "OrderPlaced":
            s.status = "placed"
        elif e.type == "PaymentAuthorized":
            s.paid = True
            s.status = "paid"
        elif e.type == "Shipped":
            s.shipped = True
            s.status = "shipped"
        elif e.type == "Delivered":
            s.delivered = True
            s.status = "delivered"
        elif e.type == "Returned":
            s.returned = True
            s.status = "returned"
    return out


class EventSourcedStore:
    """Append-only log with a `TransactionalOutbox` behind a relay."""

    def __init__(self) -> None:
        self._log: list[OrderEvent] = []
        self._outbox: list[OrderEvent] = []
        self._ids = count(1)
        self._lock = threading.Lock()

    def append(self, order_id: str, type: EventType, payload: dict,
               *, event_id: str | None = None) -> OrderEvent:
        with self._lock:
            off = next(self._ids)
            eid = event_id or f"evt-{off}"
            ev = OrderEvent(offset=off, event_id=eid, order_id=order_id,
                            type=type, payload=dict(payload))
            self._log.append(ev)
            # "Outbox write" is part of the same transaction as the log append.
            self._outbox.append(ev)
            return ev

    def read_from(self, offset: int) -> list[OrderEvent]:
        with self._lock:
            return [e for e in self._log if e.offset > offset]

    def full_log(self) -> list[OrderEvent]:
        with self._lock:
            return list(self._log)

    def outbox_pending(self) -> list[OrderEvent]:
        with self._lock:
            return list(self._outbox)

    def outbox_ack(self, offset: int) -> None:
        with self._lock:
            self._outbox = [e for e in self._outbox if e.offset != offset]


class IdempotentConsumer:
    """Applies each event at-most-once per `event_id`, tolerates redelivery."""

    def __init__(self, handler: Callable[[OrderEvent], None]) -> None:
        self._handler = handler
        self._applied: set[str] = set()
        self.failed: list[OrderEvent] = []
        self._lock = threading.Lock()

    def deliver(self, event: OrderEvent) -> bool:
        with self._lock:
            if event.event_id in self._applied:
                return False
        try:
            self._handler(event)
        except Exception:
            self.failed.append(event)
            raise
        with self._lock:
            self._applied.add(event.event_id)
        return True


class OutboxRelay:
    """Drains the store's outbox into subscribers; survives publisher crash."""

    def __init__(self, store: EventSourcedStore) -> None:
        self._store = store
        self._subs: list[IdempotentConsumer] = []

    def subscribe(self, consumer: IdempotentConsumer) -> None:
        self._subs.append(consumer)

    def drain(self) -> int:
        """Deliver every pending outbox event to every subscriber."""
        delivered = 0
        for ev in self._store.outbox_pending():
            for sub in self._subs:
                sub.deliver(ev)
            self._store.outbox_ack(ev.offset)
            delivered += 1
        return delivered
