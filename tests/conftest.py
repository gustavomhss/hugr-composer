"""
Pytest configuration and fixtures.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from unittest.mock import AsyncMock, MagicMock

import httpx

from gateway.config import GatewayConfig, GatewayYamlConfig


@pytest.fixture
def mock_config():
    """Mock gateway config for testing."""
    config = MagicMock(spec=GatewayConfig)
    config.openrouter_api_key = "test-or-key"
    config.openrouter_base_url = "https://openrouter.ai/api"
    config.groq_api_key = "test-groq-key"
    config.gemini_api_key = "test-gemini-key"
    config.nim_base_url = "http://localhost:8000"
    config.nim_api_key = "test-nim-key"
    config.mistral_api_key = "test-mistral-key"
    config.cerebras_api_key = "test-cerebras-key"
    config.opencode_bridge_endpoints = {
        "groq": "http://localhost:5001",
        "gemini": "http://localhost:5002",
        "mistral": "http://localhost:5003",
    }
    config.openrouter_model_map = {"opus-5": "anthropic/claude-opus-5"}
    config.groq_model_map = {"llama3": "llama-3.3-70b-versatile"}
    config.gemini_model_map = {"flash": "gemini-1.5-flash"}
    config.nim_model_map = {"llama3": "meta/llama-3.1-70b-instruct"}
    config.mistral_model_map = {"large": "mistral-large-latest"}
    config.cerebras_model_map = {"gpt-oss": "gpt-oss-120b"}
    config.opencode_bridge_model_map = {
        "groq": {"llama3": "groq/llama-3.3-70b-versatile"},
        "gemini": {"flash": "gemini/gemini-1.5-flash"},
    }
    config.fallback_chains = {
        "groq": ["groq", "openrouter-groq"],
        "gemini": ["gemini"],
    }
    config.max_fallback_attempts = 3
    config.request_timeout = 600.0
    config.connect_timeout = 10.0
    return config


@pytest.fixture
def mock_httpx_response():
    """Create a mock httpx response."""
    def _make(status_code: int = 200, json_data: dict = None, text: str = ""):
        response = MagicMock(spec=httpx.Response)
        response.status_code = status_code
        response.json = AsyncMock(return_value=json_data or {})
        response.text = text
        response.aread = AsyncMock(return_value=b"test")
        return response
    return _make


@pytest.fixture
def sample_anthropic_messages():
    """Sample Anthropic format messages."""
    return [
        {"role": "system", "content": "You are a helpful assistant"},
        {"role": "user", "content": "Hello, world!"},
    ]


@pytest.fixture
def sample_anthropic_tools():
    """Sample Anthropic format tools."""
    return [
        {
            "name": "read_file",
            "description": "Read a file from disk",
            "input_schema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path"}
                },
                "required": ["path"],
            },
        }
    ]


@pytest.fixture
def mock_httpx_client():
    """Mock httpx AsyncClient."""
    client = AsyncMock(spec=httpx.AsyncClient)
    return client

_REPO_ROOT = Path(__file__).resolve().parent.parent


def _outside_repo(module: object) -> bool:
    file = getattr(module, "__file__", None)
    if not file:
        return False
    try:
        Path(file).resolve().relative_to(_REPO_ROOT)
    except ValueError:
        return not any(part in ("site-packages", "lib-dynload") for part in Path(file).parts) and "python3" not in file
    return False


@pytest.fixture(autouse=True)
def _isolate_generated_imports():
    """Generated projects imported by a test (their own `app`/`core` packages) must not leak into later tests.

    Without this, a scenario test leaves the generated project's `core` in sys.modules and a later
    `from core.models import ...` in a Composer generator fails with ModuleNotFoundError.
    """
    path_before = list(sys.path)
    modules_before = dict(sys.modules)
    yield
    for name, module in list(sys.modules.items()):
        if modules_before.get(name) is module or not _outside_repo(module):
            continue
        if name in modules_before:
            sys.modules[name] = modules_before[name]
        else:
            del sys.modules[name]
    sys.path[:] = path_before
