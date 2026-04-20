"""Tests for the FastAPI `WebhookReceiverAdapter`."""

from __future__ import annotations


def test_adapter_imports_cleanly() -> None:
    from core.venous._adapters.fastapi import WebhookReceiverAdapter

    assert callable(WebhookReceiverAdapter.install)


def test_install_registers_endpoint_and_rejects_bad_signature() -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from core.venous._adapters.fastapi.WebhookReceiverAdapter import install

    app = FastAPI()
    state = install(app, hmac_key=b"secret-key-32-bytes-min-length-ok", key_id="kid-1", path="/hook")
    assert "signer" in state and "consumer" in state and "audit" in state

    client = TestClient(app)
    # Unsigned or bad signature → 401
    resp = client.post("/hook", content=b"{}", headers={"X-Signature": "ab" * 32, "X-Event-Id": "evt-1"})
    assert resp.status_code == 401


def test_valid_signature_accepted_and_duplicate_deduped() -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from core.venous._adapters.fastapi.WebhookReceiverAdapter import install

    app = FastAPI()
    key = b"very-secret-hmac-key-hex-ok-ok-ok"
    state = install(app, hmac_key=key, key_id="kid-2", path="/hook")
    body = b'{"amount":42}'
    sig = state["signer"].sign_typed(body, "kid-2", msg_type="webhook").hex()
    headers = {"X-Signature": sig, "X-Event-Id": "evt-42"}

    client = TestClient(app)
    r1 = client.post("/hook", content=body, headers=headers)
    assert r1.status_code == 200, r1.text
    assert r1.json()["received"] is True

    r2 = client.post("/hook", content=body, headers=headers)
    assert r2.status_code == 200
    # Duplicate call → audit count unchanged
    assert len(state["audit"]._events) == 1


if __name__ == "__main__":
    import sys
    tests = [test_adapter_imports_cleanly, test_install_registers_endpoint_and_rejects_bad_signature, test_valid_signature_accepted_and_duplicate_deduped]
    failed = 0
    for t in tests:
        try:
            t(); print(f"  PASS  {t.__name__}")
        except Exception as exc:  # noqa: BLE001
            print(f"  FAIL  {t.__name__}: {exc}"); failed += 1
    sys.exit(1 if failed else 0)
