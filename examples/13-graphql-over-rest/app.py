"""GraphQL over REST — DataLoader batching, depth cap, persisted queries."""
from __future__ import annotations

import hashlib
import threading
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable


class DataLoader:
    """Per-tick batching dedupe loader. load() queues, then dispatch() flushes."""

    def __init__(self, batch_fn: Callable[[list[Any]], dict[Any, Any]]) -> None:
        self._batch_fn = batch_fn
        self._queue: list[Any] = []
        self._results: dict[Any, Any] = {}
        self._calls = 0

    def load(self, key: Any) -> None:
        if key not in self._queue and key not in self._results:
            self._queue.append(key)

    def dispatch(self) -> None:
        if not self._queue:
            return
        self._calls += 1
        self._results.update(self._batch_fn(self._queue))
        self._queue = []

    def get(self, key: Any) -> Any:
        return self._results.get(key)

    @property
    def calls(self) -> int:
        return self._calls


def query_depth(query: dict, *, _d: int = 0) -> int:
    """Maximum depth of a dict-represented query tree."""
    if not isinstance(query, dict) or not query:
        return _d
    return max((query_depth(v, _d=_d + 1) for v in query.values()), default=_d)


class DepthLimitError(Exception):
    pass


def enforce_depth(query: dict, *, max_depth: int) -> None:
    d = query_depth(query)
    if d > max_depth:
        raise DepthLimitError(f"query depth {d} exceeds limit {max_depth}")


class PersistedQueryRegistry:
    """SHA-256-keyed allow-list for production query ids."""

    def __init__(self) -> None:
        self._queries: dict[str, str] = {}
        self._lock = threading.Lock()

    def register(self, query_text: str) -> str:
        qid = hashlib.sha256(query_text.encode()).hexdigest()
        with self._lock:
            self._queries[qid] = query_text
        return qid

    def resolve(self, qid: str) -> str | None:
        with self._lock:
            return self._queries.get(qid)


@dataclass
class FieldACL:
    """Field → required role; missing role returns (null, error), not 403."""
    required_roles: dict[str, str] = field(default_factory=dict)

    def guard(self, field_name: str, user_roles: set[str]) -> tuple[bool, str | None]:
        req = self.required_roles.get(field_name)
        if req is None or req in user_roles:
            return True, None
        return False, f"unauthorized field '{field_name}' requires role '{req}'"


@dataclass
class GraphQLResult:
    data: dict
    errors: list[dict] = field(default_factory=list)


def resolve_orders_query(
    *, order_ids: list[str], orders_loader: DataLoader,
    customers_loader: DataLoader, products_loader: DataLoader,
    acl: FieldACL, user_roles: set[str],
    max_depth: int = 15,
    shape: dict | None = None,
) -> GraphQLResult:
    """Resolve an orders+customers+products query with 3 batched calls.

    The resolver runs in phases:
      1. queue all order loads  → dispatch (1 call)
      2. queue customer + product ids from the results → dispatch each (2 calls)
    """
    shape = shape or {"order": {"customer": {}, "product": {}}}
    enforce_depth(shape, max_depth=max_depth)

    for oid in order_ids:
        orders_loader.load(oid)
    orders_loader.dispatch()

    result: dict[str, Any] = {"orders": []}
    errors: list[dict] = []
    cust_ids = []
    prod_ids = []
    orders = [orders_loader.get(oid) for oid in order_ids]
    for o in orders:
        if o is None:
            continue
        cust_ids.append(o["customer_id"])
        prod_ids.append(o["product_id"])
    for c in cust_ids:
        customers_loader.load(c)
    for p in prod_ids:
        products_loader.load(p)
    customers_loader.dispatch()
    products_loader.dispatch()

    for oid, o in zip(order_ids, orders):
        if o is None:
            continue
        row: dict[str, Any] = {"id": oid}
        # customer: simple field (always allowed for this example).
        row["customer"] = customers_loader.get(o["customer_id"])
        # product: ACL-guarded.
        ok, err = acl.guard("product", user_roles)
        if ok:
            row["product"] = products_loader.get(o["product_id"])
        else:
            row["product"] = None
            errors.append({"field": "product", "message": err})
        result["orders"].append(row)
    return GraphQLResult(data=result, errors=errors)
