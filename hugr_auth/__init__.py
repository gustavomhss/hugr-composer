"""HuGR platform auth service — license issuance + introspection.

Separate from the skill catalog (skills/) on purpose: this is HuGR's own
infrastructure (the authority that gates the hosted MCP server), not a product
the customer composes. The MCP gate (skills/.../mcp_tools/auth_gate.py) is a
dumb client — it forwards a license key here and trusts the verdict; only this
service holds the signing secret.
"""
