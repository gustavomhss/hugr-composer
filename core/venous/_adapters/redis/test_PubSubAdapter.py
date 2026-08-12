"""Behavioral tests for ``RedisPubSubBackend``.

Strategy: inject a fake ``redis.asyncio`` module via ``sys.modules`` so
every call path runs against a deterministic in-process stand-in — no
network, no Docker. The fake mimics the subset of the redis.asyncio
surface that the adapter uses (``from_url``, ``publish``, ``pubsub()``
async context manager, ``pubsub.subscribe``/``listen``/``unsubscribe``).

We test:

1. Lazy import — constructing the backend + reading ``.url`` does NOT
   try to import redis.
2. Publish surfaces ``PubSubRedisNotInstalled`` with the actionable
   install hint when redis is missing.
3. Closed backend rejects publish AND subscribe (symmetric with the
   motor's closed semantics).
4. Invalid topic rejected by BOTH publish and subscribe
   (PS_INV_03 at adapter level).
5. Publish encodes as JSON.
6. TypeError raised for non-JSON-serialisable payloads.
7. Subscribe yields only ``type=message`` frames, decoded via JSON.
8. Subscribe skips handshake frames silently (subscribe / unsubscribe).
9. Subscribe ``finally`` unsubscribes (PS_INV_04 witness at adapter level).
10. close() is idempotent and invokes the client's aclose() / close().
11. URL defaults to env REDIS_URL when not provided; falls back to
    ``redis://localhost:6379/0`` when env is absent.
12. Explicit URL takes precedence over env.
"""
from __future__ import annotations

import asyncio
import json
import sys
from typing import Any

import pytest


# ---------------------------------------------------------------------------
# Fake redis.asyncio module
# ---------------------------------------------------------------------------
class _FakePubSubClient:
    def __init__(self) -> None:
        self.subscribed: list[str] = []
        self.unsubscribed: list[str] = []
        self._queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._closed = False

    async def __aenter__(self) -> _FakePubSubClient:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        self._closed = True

    async def subscribe(self, topic: str) -> None:
        self.subscribed.append(topic)
        # simulate Redis subscribe-ack frame
        await self._queue.put({"type": "subscribe", "data": 1, "channel": topic})

    async def unsubscribe(self, topic: str) -> None:
        self.unsubscribed.append(topic)
        # drop a sentinel so listen() loop can exit the generator cleanly
        await self._queue.put({"type": "unsubscribe", "data": 0, "channel": topic})
        await self._queue.put(None)  # type: ignore[arg-type]

    async def listen(self):
        while True:
            item = await self._queue.get()
            if item is None:
                return
            yield item

    # Test-only helpers
    async def inject_message(self, topic: str, raw: str) -> None:
        await self._queue.put({"type": "message", "channel": topic, "data": raw})

    async def inject_raw(self, frame: Any) -> None:
        await self._queue.put(frame)


class _FakeRedisClient:
    def __init__(self) -> None:
        self.published: list[tuple[str, str]] = []
        self._pubsub = _FakePubSubClient()
        self.closed = False

    async def publish(self, topic: str, data: str) -> None:
        self.published.append((topic, data))

    def pubsub(self) -> _FakePubSubClient:
        return self._pubsub

    async def aclose(self) -> None:
        self.closed = True


class _FakeRedisAsyncModule:
    def __init__(self) -> None:
        self.last_url: str | None = None
        self.last_decode_responses: bool | None = None
        self.client = _FakeRedisClient()

    def from_url(self, url: str, *, decode_responses: bool = False) -> _FakeRedisClient:
        self.last_url = url
        self.last_decode_responses = decode_responses
        return self.client


class _FakeRedisPackage:
    def __init__(self) -> None:
        self.asyncio = _FakeRedisAsyncModule()


@pytest.fixture()
def fake_redis(monkeypatch: pytest.MonkeyPatch) -> _FakeRedisPackage:
    pkg = _FakeRedisPackage()
    monkeypatch.setitem(sys.modules, "redis", pkg)
    monkeypatch.setitem(sys.modules, "redis.asyncio", pkg.asyncio)
    return pkg


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
from core.venous._adapters.redis import (  # noqa: E402  (import after fixture definitions)
    PubSubRedisNotInstalled,
    RedisPubSubBackend,
)
from core.venous.events.PubSub import PubSubClosed, PubSubInvariantError  # noqa: E402


def test_lazy_import_construction_never_imports_redis(monkeypatch: pytest.MonkeyPatch) -> None:
    # Pretend redis is not installed — constructing + reading .url must NOT raise.
    monkeypatch.setitem(sys.modules, "redis", None)
    monkeypatch.setitem(sys.modules, "redis.asyncio", None)
    b = RedisPubSubBackend("redis://example:6379/1")
    assert b.url == "redis://example:6379/1"
    assert b.closed is False


def test_publish_raises_when_redis_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    # Simulate missing redis package: remove from sys.modules AND block import.
    monkeypatch.delitem(sys.modules, "redis", raising=False)
    monkeypatch.delitem(sys.modules, "redis.asyncio", raising=False)

    import builtins
    orig_import = builtins.__import__

    def _blocked_import(name: str, *a: Any, **k: Any) -> Any:
        if name == "redis" or name.startswith("redis."):
            raise ImportError(f"no module named {name!r}")
        return orig_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", _blocked_import)

    async def _go() -> None:
        b = RedisPubSubBackend("redis://x/0")
        with pytest.raises(PubSubRedisNotInstalled) as exc_info:
            await b.publish("t", {"x": 1})
        assert "pip install redis" in str(exc_info.value)

    asyncio.run(_go())


def test_closed_backend_rejects_publish_and_subscribe(fake_redis: _FakeRedisPackage) -> None:
    async def _go() -> None:
        b = RedisPubSubBackend("redis://x/0")
        await b.close()
        assert b.closed is True

        with pytest.raises(PubSubClosed):
            await b.publish("t", {"x": 1})

        with pytest.raises(PubSubClosed):
            ait = b.subscribe("t")
            await ait.__anext__()

    asyncio.run(_go())


def test_invalid_topic_rejected_symmetrically(fake_redis: _FakeRedisPackage) -> None:
    async def _go() -> None:
        b = RedisPubSubBackend("redis://x/0")
        for bad in ("", 123, None):
            with pytest.raises(PubSubInvariantError):
                await b.publish(bad, {"x": 1})  # type: ignore[arg-type]
            with pytest.raises(PubSubInvariantError):
                ait = b.subscribe(bad)  # type: ignore[arg-type]
                await ait.__anext__()
    asyncio.run(_go())


def test_publish_encodes_as_json(fake_redis: _FakeRedisPackage) -> None:
    async def _go() -> None:
        b = RedisPubSubBackend("redis://x/0")
        await b.publish("items", {"id": 1, "title": "hello"})
        assert fake_redis.asyncio.client.published == [
            ("items", json.dumps({"id": 1, "title": "hello"})),
        ]
    asyncio.run(_go())


def test_publish_rejects_non_json_payload(fake_redis: _FakeRedisPackage) -> None:
    async def _go() -> None:
        b = RedisPubSubBackend("redis://x/0")
        with pytest.raises(TypeError):
            await b.publish("items", object())  # not JSON-serialisable
    asyncio.run(_go())


def test_subscribe_yields_decoded_messages(fake_redis: _FakeRedisPackage) -> None:
    async def _go() -> None:
        b = RedisPubSubBackend("redis://x/0")
        got: list[object] = []

        async def consumer() -> None:
            async for payload in b.subscribe("items"):
                got.append(payload)
                if payload == "stop":
                    return

        task = asyncio.create_task(consumer())
        await asyncio.sleep(0)

        client = fake_redis.asyncio.client._pubsub
        await client.inject_message("items", json.dumps({"id": 1}))
        await client.inject_message("items", json.dumps("stop"))
        await task

        assert got == [{"id": 1}, "stop"]
    asyncio.run(_go())


def test_subscribe_skips_handshake_and_non_dict_frames(fake_redis: _FakeRedisPackage) -> None:
    async def _go() -> None:
        b = RedisPubSubBackend("redis://x/0")
        got: list[object] = []

        async def consumer() -> None:
            async for payload in b.subscribe("items"):
                got.append(payload)
                if payload == "stop":
                    return

        task = asyncio.create_task(consumer())
        await asyncio.sleep(0)

        client = fake_redis.asyncio.client._pubsub
        # non-dict frame (should be skipped silently)
        await client.inject_raw("garbage")
        # handshake frame (ignored)
        await client.inject_raw({"type": "subscribe", "data": 1})
        # frame without data
        await client.inject_raw({"type": "message", "data": None})
        # real frame
        await client.inject_message("items", json.dumps("stop"))
        await task

        assert got == ["stop"]
    asyncio.run(_go())


def test_subscribe_unsubscribes_on_finally(fake_redis: _FakeRedisPackage) -> None:
    async def _go() -> None:
        b = RedisPubSubBackend("redis://x/0")
        ait = b.subscribe("items")

        async def consumer() -> None:
            try:
                async for _ in ait:
                    return
            finally:
                await ait.aclose()

        task = asyncio.create_task(consumer())
        await asyncio.sleep(0)

        client = fake_redis.asyncio.client._pubsub
        await client.inject_message("items", json.dumps("x"))
        await task

        # PS_INV_04 witness at adapter level: unsubscribe MUST have fired.
        assert client.unsubscribed == ["items"]
    asyncio.run(_go())


def test_close_is_idempotent_and_closes_client(fake_redis: _FakeRedisPackage) -> None:
    async def _go() -> None:
        b = RedisPubSubBackend("redis://x/0")
        # Touch client once so it's instantiated.
        await b.publish("items", "x")
        assert fake_redis.asyncio.client.closed is False
        await b.close()
        assert fake_redis.asyncio.client.closed is True
        await b.close()  # idempotent
        assert b.closed is True
    asyncio.run(_go())


def test_url_defaults_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REDIS_URL", "redis://env.example:6379/7")
    b = RedisPubSubBackend()
    assert b.url == "redis://env.example:6379/7"


def test_url_falls_back_to_localhost_when_env_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("REDIS_URL", raising=False)
    b = RedisPubSubBackend()
    assert b.url == "redis://localhost:6379/0"


def test_explicit_url_takes_precedence_over_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REDIS_URL", "redis://env-x/0")
    b = RedisPubSubBackend("redis://explicit/1")
    assert b.url == "redis://explicit/1"
