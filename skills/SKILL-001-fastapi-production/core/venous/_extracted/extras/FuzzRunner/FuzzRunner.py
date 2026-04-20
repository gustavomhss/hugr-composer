from __future__ import annotations
from typing import Any
import os
import time


class FuzzRunner:
    """Orchestrates fuzzing: fetch schema, generate payloads, run requests.

    Args:
        base_url: Target server base URL.
        iterations: Number of payloads to try per endpoint.
        timeout_s: Per-request timeout in seconds.
    """

    def __init__(self, base_url: str, iterations: int | None=None, timeout_s: int | None=None) -> None:
        self.base_url = base_url.rstrip('/')
        self.iterations = iterations or int(os.getenv('FUZZ_ITERATIONS', '10'))
        self.timeout_s = timeout_s or int(os.getenv('FUZZ_TIMEOUT_S', '5'))

    async def run(self) -> list[FuzzResult]:
        """Fetch the schema, generate payloads, and run all fuzz requests.

        Returns:
            List of FuzzResult objects.  Filter with ``.is_finding()`` for
            actionable issues only.
        """
        import httpx
        from app.fuzzer import APIFuzzer
        async with httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout_s) as client:
            schema = await self._fetch_schema(client)
            fuzzer = APIFuzzer(self.base_url, schema=schema)
            endpoints = fuzzer.endpoint_list()
            logger.info('Fuzzing %d endpoints (%d iterations each)', len(endpoints), self.iterations)
            results: list[FuzzResult] = []
            for ep in endpoints:
                payloads = fuzzer.generate_payloads(ep['body_schema'])
                for payload in payloads[:self.iterations]:
                    result = await self._fuzz_one(client, ep['method'], ep['path'], payload)
                    results.append(result)
            return results

    async def _fetch_schema(self, client: Any) -> dict[str, Any]:
        """Download the OpenAPI schema from the target server.

        Args:
            client: Async httpx client.

        Returns:
            OpenAPI schema dict.
        """
        try:
            resp = await client.get('/openapi.json')
            return resp.json()
        except Exception as exc:
            logger.warning('Failed to fetch schema: %s', exc)
            return {}

    async def _fuzz_one(self, client: Any, method: str, path: str, payload: dict[str, Any]) -> FuzzResult:
        """Send one adversarial request and return a FuzzResult.

        Args:
            client: Async httpx client.
            method: HTTP method (POST, PUT, PATCH).
            path: Endpoint path to target.
            payload: Adversarial body payload.

        Returns:
            FuzzResult describing the outcome.
        """
        t0 = time.monotonic()
        try:
            resp = await client.request(method, path, json=payload)
            elapsed = int((time.monotonic() - t0) * 1000)
            is_json = True
            try:
                resp.json()
            except Exception:
                is_json = False
            return FuzzResult(method, path, payload, resp.status_code, is_json, elapsed)
        except Exception as exc:
            elapsed = int((time.monotonic() - t0) * 1000)
            return FuzzResult(method, path, payload, 0, False, elapsed, error=str(exc))
