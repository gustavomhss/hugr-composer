"""
SKILL-001 Payments Tool: Static analysis of payment code for security and correctness.

Performs AST-based and regex analysis on a FastAPI project to detect 8 common
payment integration anti-patterns: missing webhook signature verification,
no idempotency keys, raw card data handling, missing error handling,
hardcoded API keys, fulfillment on redirect (not webhook), missing refund
endpoint, and no event deduplication.
"""

from __future__ import annotations

import ast
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
from core.models import Finding, Severity

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_EXCLUDE_DIRS: set[str] = {
    ".venv", "venv", "node_modules", "__pycache__", ".git",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", "dist", "build",
    "site-packages",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _collect_python_files(root: Path) -> list[Path]:
    """Walk *root* and return .py files not in excluded directories."""
    files: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _DEFAULT_EXCLUDE_DIRS]
        dp = Path(dirpath)
        for fn in filenames:
            if fn.endswith(".py"):
                files.append(dp / fn)
    return files


def _has_stripe_code(source: str) -> bool:
    """Check if source contains Stripe-related code."""
    return bool(re.search(
        r"(import\s+stripe|from\s+stripe|stripe\.|STRIPE_|webhook.*stripe)",
        source, re.IGNORECASE,
    ))


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------


def _check_pay01_webhook_signature(source: str, filepath: Path) -> Finding | None:
    """PAY-01: Webhook endpoint verifies Stripe signature."""
    has_webhook = bool(re.search(
        r"""(webhook|["']/webhooks?/stripe["'])""",
        source, re.IGNORECASE,
    ))
    if not has_webhook:
        return None

    has_verification = (
        "construct_event" in source
        or "Webhook.construct_event" in source
        or "SignatureVerificationError" in source
        or "stripe-signature" in source.lower()
    )

    if not has_verification:
        return Finding(
            rule_id="PAY-01",
            severity=Severity.CRITICAL,
            title="Webhook endpoint without signature verification",
            description=(
                "Stripe webhook endpoint found but no signature verification "
                "using stripe.Webhook.construct_event(). Without verification, "
                "anyone can POST fake webhook events to trigger false order "
                "fulfillments, subscription activations, or refund processing."
            ),
            file_path=str(filepath),
            fix_suggestion=(
                "Use stripe.Webhook.construct_event(payload, sig_header, secret) "
                "to verify every webhook. Read the raw request body (not parsed "
                "JSON) and the stripe-signature header."
            ),
        )
    return None


def _check_pay02_idempotency(source: str, filepath: Path) -> Finding | None:
    """PAY-02: Stripe write operations use idempotency keys."""
    # Check for Stripe write operations
    write_ops = [
        "Session.create", "Charge.create", "PaymentIntent.create",
        "Subscription.create", "Refund.create", "Invoice.create",
    ]
    has_write_op = any(op in source for op in write_ops)
    if not has_write_op:
        return None

    has_idempotency = "idempotency_key" in source

    if not has_idempotency:
        return Finding(
            rule_id="PAY-02",
            severity=Severity.HIGH,
            title="Stripe write operations without idempotency keys",
            description=(
                "Stripe API write operations found without idempotency_key. "
                "Without idempotency, network retries or duplicate requests "
                "can create duplicate charges, subscriptions, or refunds. "
                "This is not optional for financial operations."
            ),
            file_path=str(filepath),
            fix_suggestion=(
                "Add idempotency_key to all Stripe .create() calls. "
                "Use deterministic keys from business data: "
                "idempotency_key=f'checkout:{order_id}'"
            ),
        )
    return None


def _check_pay03_raw_card_data(source: str, filepath: Path) -> Finding | None:
    """PAY-03: No raw card data in server code (PCI compliance)."""
    # Check for card data field names in request models or function signatures
    card_patterns = [
        r"card_number", r"card_num", r"ccn", r"cvv", r"cvc",
        r"expiry_month", r"expiry_year", r"card_exp",
        r"pan\b",  # Primary Account Number
    ]

    for pattern in card_patterns:
        match = re.search(pattern, source, re.IGNORECASE)
        if match:
            # Find the line number
            line_num = source[:match.start()].count("\n") + 1
            return Finding(
                rule_id="PAY-03",
                severity=Severity.CRITICAL,
                title=f"Raw card data field detected: '{match.group()}'",
                description=(
                    f"Code references raw card data ('{match.group()}'). "
                    f"Card data must NEVER touch your server. This puts you "
                    f"in PCI DSS SAQ D scope (329 compliance questions). "
                    f"Use Stripe Checkout or Stripe Elements so card data goes "
                    f"directly to Stripe (SAQ A — 22 questions)."
                ),
                file_path=str(filepath),
                line_number=line_num,
                fix_suggestion=(
                    "Remove all card data fields from your server code. "
                    "Use Stripe Checkout Sessions (hosted page) or Stripe "
                    "Elements (frontend tokenization). Your server should "
                    "only receive payment_method_id or session_id — never "
                    "card numbers."
                ),
            )
    return None


def _check_pay04_error_handling(source: str, filepath: Path) -> Finding | None:
    """PAY-04: Stripe API calls have proper error handling."""
    if not _has_stripe_code(source):
        return None

    # Check for Stripe API calls
    has_api_call = bool(re.search(r"stripe\.\w+\.\w+\(", source))
    if not has_api_call:
        return None

    has_error_handling = (
        "stripe.error" in source
        or "StripeError" in source
        or "CardError" in source
        or "InvalidRequestError" in source
    )

    if not has_error_handling:
        return Finding(
            rule_id="PAY-04",
            severity=Severity.HIGH,
            title="Stripe API calls without error handling",
            description=(
                "Stripe API calls found without stripe.error exception "
                "handling. Stripe API can raise CardError (decline), "
                "InvalidRequestError (bad params), AuthenticationError "
                "(wrong key), or APIConnectionError (network). Unhandled "
                "errors return 500 to the user with no useful message."
            ),
            file_path=str(filepath),
            fix_suggestion=(
                "Wrap Stripe calls in try/except stripe.error.StripeError. "
                "Return user-friendly error messages from exc.user_message."
            ),
        )
    return None


def _check_pay05_hardcoded_keys(source: str, filepath: Path) -> Finding | None:
    """PAY-05: Stripe API keys not hardcoded."""
    # Check for hardcoded Stripe keys
    key_patterns = [
        (r"sk_live_[a-zA-Z0-9]{20,}", "live secret key"),
        (r"sk_test_[a-zA-Z0-9]{20,}", "test secret key"),
        (r"pk_live_[a-zA-Z0-9]{20,}", "live publishable key"),
        (r"whsec_[a-zA-Z0-9]{20,}", "webhook signing secret"),
    ]

    for pattern, key_type in key_patterns:
        match = re.search(pattern, source)
        if match:
            line_num = source[:match.start()].count("\n") + 1
            severity = Severity.CRITICAL if "live" in key_type else Severity.HIGH
            return Finding(
                rule_id="PAY-05",
                severity=severity,
                title=f"Hardcoded Stripe {key_type} in source code",
                description=(
                    f"A Stripe {key_type} is hardcoded in source code "
                    f"(line {line_num}). This key will be visible in version "
                    f"control. Live keys allow real charges on real cards."
                ),
                file_path=str(filepath),
                line_number=line_num,
                fix_suggestion=(
                    "Remove the key immediately. Load from environment: "
                    "os.getenv('STRIPE_SECRET_KEY'). Rotate the exposed key "
                    "in the Stripe Dashboard."
                ),
            )

    # Also check for assignment patterns
    assign_re = re.compile(
        r"""(stripe\.api_key|STRIPE_SECRET_KEY|stripe_key)\s*=\s*["']([^"']{10,})["']""",
        re.IGNORECASE,
    )
    for match in assign_re.finditer(source):
        value = match.group(2)
        # Allow env var patterns
        if "getenv" in source[max(0, match.start()-50):match.end()+50]:
            continue
        if value.startswith("sk_") or value.startswith("pk_") or value.startswith("whsec_"):
            line_num = source[:match.start()].count("\n") + 1
            return Finding(
                rule_id="PAY-05",
                severity=Severity.CRITICAL,
                title="Hardcoded Stripe API key in assignment",
                description=(
                    f"Stripe API key appears hardcoded at line {line_num}. "
                    f"This is a security vulnerability visible in version control."
                ),
                file_path=str(filepath),
                line_number=line_num,
                fix_suggestion="Use os.getenv('STRIPE_SECRET_KEY') instead.",
            )

    return None


def _check_pay06_fulfillment_on_redirect(source: str, filepath: Path) -> Finding | None:
    """PAY-06: Order fulfillment happens via webhook, not on redirect."""
    # Check for success_url processing that triggers fulfillment
    has_success_redirect = bool(re.search(
        r"""success.*session_id|payment/success.*fulfill|redirect.*paid""",
        source, re.IGNORECASE,
    ))

    if not has_success_redirect:
        return None

    # Check if there's actual fulfillment logic tied to the redirect
    has_fulfill_on_redirect = bool(re.search(
        r"""@\w+\.(get|post)\s*\(\s*["'].*success.*["']\s*\).*?(?:fulfill|process_order|grant_access|create_order)""",
        source, re.DOTALL | re.IGNORECASE,
    ))

    if has_fulfill_on_redirect:
        return Finding(
            rule_id="PAY-06",
            severity=Severity.HIGH,
            title="Order fulfillment triggered on redirect, not webhook",
            description=(
                "Order fulfillment logic appears to be triggered by the "
                "success redirect URL, not by a webhook event. Users can "
                "close the browser tab before redirect completes, or "
                "manipulate the URL. Webhooks are the only reliable "
                "signal for payment confirmation."
            ),
            file_path=str(filepath),
            fix_suggestion=(
                "Move fulfillment logic to the checkout.session.completed "
                "webhook handler. The success URL should only show a "
                "'thank you' message, not process the order."
            ),
        )
    return None


def _check_pay07_refund_endpoint(all_sources: str) -> Finding | None:
    """PAY-07: Refund endpoint exists."""
    if not _has_stripe_code(all_sources):
        return None

    has_charges = (
        "Charge.create" in all_sources
        or "Session.create" in all_sources
        or "PaymentIntent.create" in all_sources
    )
    if not has_charges:
        return None

    has_refund = (
        "Refund.create" in all_sources
        or "/refund" in all_sources.lower()
        or "refund" in all_sources.lower()
    )

    if not has_refund:
        return Finding(
            rule_id="PAY-07",
            severity=Severity.MEDIUM,
            title="No refund endpoint or logic",
            description=(
                "Payment creation found but no refund handling. In production, "
                "you need programmatic refund capabilities for customer support, "
                "dispute resolution, and automated refund policies."
            ),
            fix_suggestion=(
                "Add a refund endpoint: stripe.Refund.create(payment_intent=..., "
                "amount=..., idempotency_key=...). Support both full and "
                "partial refunds."
            ),
        )
    return None


def _check_pay08_event_dedup(source: str, filepath: Path) -> Finding | None:
    """PAY-08: Webhook handlers deduplicate events (idempotent processing)."""
    has_handler = bool(re.search(
        r"(handle_checkout|handle_subscription|handle_invoice|webhook.*handler)",
        source, re.IGNORECASE,
    ))
    if not has_handler:
        return None

    has_dedup = (
        "already_processed" in source
        or "existing" in source
        or "processed_events" in source
        or "event_id" in source
        or "idempotent" in source.lower()
        or "upsert" in source.lower()
        or "get_or_create" in source.lower()
    )

    if not has_dedup:
        return Finding(
            rule_id="PAY-08",
            severity=Severity.HIGH,
            title="Webhook handlers without event deduplication",
            description=(
                "Webhook event handlers found without deduplication logic. "
                "Stripe may deliver the same webhook event multiple times "
                "(retries on failure). Without deduplication, you may "
                "fulfill orders twice, send duplicate emails, or create "
                "duplicate database records."
            ),
            file_path=str(filepath),
            fix_suggestion=(
                "Check if event was already processed before acting: "
                "store processed event IDs with a UNIQUE constraint. "
                "Use upsert (INSERT ON CONFLICT DO NOTHING) for safety."
            ),
        )
    return None


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def verify_payment_config(project_path: str) -> list[Finding]:
    """
    Statically analyze a FastAPI project for payment integration issues.

    Scans all Python files for 8 common payment anti-patterns using
    regex matching and source analysis. Returns a list of Finding objects,
    sorted by severity (critical first).

    Checks:
        PAY-01: Webhook signature verification
        PAY-02: Idempotency keys on write operations
        PAY-03: No raw card data (PCI compliance)
        PAY-04: Stripe error handling
        PAY-05: No hardcoded API keys
        PAY-06: Fulfillment via webhook, not redirect
        PAY-07: Refund endpoint exists
        PAY-08: Webhook event deduplication

    Args:
        project_path: Root directory of the FastAPI project to analyze.

    Returns:
        List of Finding objects for each detected issue.

    Example::

        findings = verify_payment_config("/path/to/my-fastapi-project")
        for f in findings:
            print(f"[{f.severity.value}] {f.rule_id}: {f.title}")
        # [critical] PAY-01: Webhook endpoint without signature verification
        # [critical] PAY-03: Raw card data field detected: 'card_number'
    """
    root = Path(project_path).resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"Project path does not exist: {root}")

    py_files = _collect_python_files(root)
    findings: list[Finding] = []
    all_sources_parts: list[str] = []

    for filepath in py_files:
        try:
            source = filepath.read_text(encoding="utf-8", errors="replace")
        except (OSError, UnicodeDecodeError):
            continue

        all_sources_parts.append(source)

        # --- Per-file checks ---

        # PAY-01: Webhook signature
        finding = _check_pay01_webhook_signature(source, filepath)
        if finding:
            findings.append(finding)

        # PAY-02: Idempotency keys
        finding = _check_pay02_idempotency(source, filepath)
        if finding:
            findings.append(finding)

        # PAY-03: Raw card data
        finding = _check_pay03_raw_card_data(source, filepath)
        if finding:
            findings.append(finding)

        # PAY-04: Error handling
        finding = _check_pay04_error_handling(source, filepath)
        if finding:
            findings.append(finding)

        # PAY-05: Hardcoded keys
        finding = _check_pay05_hardcoded_keys(source, filepath)
        if finding:
            findings.append(finding)

        # PAY-06: Fulfillment on redirect
        finding = _check_pay06_fulfillment_on_redirect(source, filepath)
        if finding:
            findings.append(finding)

        # PAY-08: Event deduplication
        finding = _check_pay08_event_dedup(source, filepath)
        if finding:
            findings.append(finding)

    # --- Project-wide checks ---
    all_sources = "\n".join(all_sources_parts)

    # PAY-07: Refund endpoint
    finding = _check_pay07_refund_endpoint(all_sources)
    if finding:
        findings.append(finding)

    # Sort by severity
    severity_order = {
        Severity.CRITICAL: 0,
        Severity.HIGH: 1,
        Severity.MEDIUM: 2,
        Severity.LOW: 3,
    }
    findings.sort(key=lambda f: severity_order.get(f.severity, 99))

    return findings
