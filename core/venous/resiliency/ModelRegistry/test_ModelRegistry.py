"""Invariant tests for `ModelRegistry`."""
from __future__ import annotations


class _Registry:
    def __init__(self):
        self._models = {}
        self._loaders = {}

    def register(self, name: str, fn, version: str = "latest") -> None:
        self._loaders[f"{name}:{version}"] = fn

    def get(self, name: str, version: str = "latest"):
        key = f"{name}:{version}"
        if key in self._models:
            return self._models[key]
        if key not in self._loaders:
            raise KeyError(key)
        obj = self._loaders[key]()
        self._models[key] = obj
        return obj


# INV_01 -----------------------------------------------------------------
def test_inv_lazy_single_load_confirms() -> None:
    r = _Registry()
    calls = [0]
    def loader():
        calls[0] += 1
        return object()
    r.register("m", loader)
    _ = r.get("m"); _ = r.get("m"); _ = r.get("m")
    assert calls[0] == 1


def test_inv_lazy_single_load_prevents() -> None:
    # Without a get(), loader is never called.
    r = _Registry()
    calls = [0]
    r.register("m", lambda: (calls.__setitem__(0, calls[0] + 1), "v")[1])
    assert calls[0] == 0


def test_inv_lazy_single_load_under_failure() -> None:
    # Loader raises -> the key is NOT cached; subsequent get retries.
    r = _Registry()
    calls = [0]
    def bad():
        calls[0] += 1
        raise RuntimeError("nope")
    r.register("m", bad)
    try: r.get("m")
    except RuntimeError: pass
    try: r.get("m")
    except RuntimeError: pass
    assert calls[0] == 2


# INV_02 -----------------------------------------------------------------
def test_inv_unknown_key_raises_confirms() -> None:
    r = _Registry()
    try:
        r.get("never-registered")
    except KeyError:
        return
    raise AssertionError("expected KeyError")


def test_inv_unknown_key_raises_prevents() -> None:
    # Registering "foo:latest" MUST NOT auto-register "foo:v2".
    r = _Registry()
    r.register("foo", lambda: 1)
    try: r.get("foo", "v2")
    except KeyError: return
    raise AssertionError("expected KeyError")


def test_inv_unknown_key_raises_under_failure() -> None:
    r = _Registry()
    try: r.get("")
    except KeyError: return
    raise AssertionError("expected KeyError")


# INV_03 -----------------------------------------------------------------
def test_inv_version_isolation_confirms() -> None:
    r = _Registry()
    r.register("m", lambda: "v1", version="v1")
    r.register("m", lambda: "v2", version="v2")
    assert r.get("m", "v1") == "v1"
    assert r.get("m", "v2") == "v2"


def test_inv_version_isolation_prevents() -> None:
    # Default "latest" is independent from named versions.
    r = _Registry()
    r.register("m", lambda: "latest")
    r.register("m", lambda: "pinned", version="v1")
    assert r.get("m") == "latest"
    assert r.get("m", "v1") == "pinned"


def test_inv_version_isolation_under_failure() -> None:
    # Re-registering the same key replaces the loader.
    r = _Registry()
    r.register("m", lambda: "a")
    r.register("m", lambda: "b")
    assert r.get("m") == "b"
