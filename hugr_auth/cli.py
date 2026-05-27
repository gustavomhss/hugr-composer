"""Ops CLI for HuGR licenses — issue / cancel / revoke.

For operators who hold the signing secret (issuance) or the store path
(revocation), without going through the HTTP admin endpoints. The billing
system normally uses the HTTP endpoints; this is the break-glass / scripting
path.

Usage::

    HUGR_LICENSE_SIGNING_SECRET=<hex> python -m hugr_auth.cli issue --seat acme --plan pro --ttl-days 30
    HUGR_STORE_PATH=subs.json        python -m hugr_auth.cli cancel --seat acme
    HUGR_STORE_PATH=subs.json        python -m hugr_auth.cli revoke --jti <jti>
"""

from __future__ import annotations

import argparse
import os
import sys

from hugr_auth.license import introspect_license, mint_license
from hugr_auth.store import FileSubscriptionStore


def _secret() -> bytes:
    raw = os.getenv("HUGR_LICENSE_SIGNING_SECRET", "")
    if not raw:
        sys.exit("HUGR_LICENSE_SIGNING_SECRET not set")
    try:
        return bytes.fromhex(raw)
    except ValueError:
        return raw.encode("utf-8")


def _store():
    """Revocation store for cancel/revoke, matching the API's precedence.

    ``HUGR_STORE_DSN`` (SQLAlchemy URL, e.g. Postgres) wins so the CLI writes to
    the *same shared* deny-list the running API reads; else ``HUGR_STORE_PATH``
    (JSON file). One of the two MUST be set — there is no in-memory CLI path
    (it would mutate a throwaway store and silently no-op).
    """
    dsn = os.getenv("HUGR_STORE_DSN", "").strip()
    if dsn:
        from hugr_auth.store_sql import SqlSubscriptionStore  # noqa: PLC0415

        return SqlSubscriptionStore(dsn)
    path = os.getenv("HUGR_STORE_PATH", "")
    if not path:
        sys.exit("set HUGR_STORE_DSN (preferred) or HUGR_STORE_PATH")
    return FileSubscriptionStore(path)


def cmd_issue(args: argparse.Namespace) -> int:
    key = mint_license(
        _secret(),
        seat=args.seat,
        plan=args.plan,
        scopes=args.scopes.split(",") if args.scopes else None,
        ttl_seconds=args.ttl_days * 24 * 3600,
    )
    claims = introspect_license(_secret(), key) or {}
    print(key)
    print(f"# seat={args.seat} plan={args.plan} jti={claims.get('jti')} exp={claims.get('expires_at')}",
          file=sys.stderr)
    return 0


def cmd_cancel(args: argparse.Namespace) -> int:
    _store().cancel_seat(args.seat)
    print(f"cancelled seat {args.seat}", file=sys.stderr)
    return 0


def cmd_revoke(args: argparse.Namespace) -> int:
    _store().revoke_key(args.jti)
    print(f"revoked key {args.jti}", file=sys.stderr)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="hugr-license", description="HuGR license ops")
    sub = p.add_subparsers(dest="cmd", required=True)

    pi = sub.add_parser("issue", help="mint a license key for a seat")
    pi.add_argument("--seat", required=True)
    pi.add_argument("--plan", default="pro")
    pi.add_argument("--scopes", default="", help="comma-separated; default hugr:tools")
    pi.add_argument("--ttl-days", type=int, default=30, dest="ttl_days")
    pi.set_defaults(func=cmd_issue)

    pc = sub.add_parser("cancel", help="cancel a seat (deny all its keys)")
    pc.add_argument("--seat", required=True)
    pc.set_defaults(func=cmd_cancel)

    pr = sub.add_parser("revoke", help="revoke a single key by jti")
    pr.add_argument("--jti", required=True)
    pr.set_defaults(func=cmd_revoke)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
