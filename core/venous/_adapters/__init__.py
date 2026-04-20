"""Framework adapters over framework-agnostic primitives.

See `/docs/decisions/0003-adapter-layer.md`. Only this subtree may import
framework SDKs (FastAPI, Starlette, SQLAlchemy); primitives themselves
must stay framework-free per CONTRACT.md §B1.0.1.
"""
