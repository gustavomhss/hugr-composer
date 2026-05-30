"""Conftest for realtime behavior tests.

Restricts anyio to asyncio backend only — the generated scaffold uses
structlog with asyncio-native async logging that is incompatible with trio.
"""

import pytest


@pytest.fixture(params=["asyncio"])
def anyio_backend(request):
    return request.param
