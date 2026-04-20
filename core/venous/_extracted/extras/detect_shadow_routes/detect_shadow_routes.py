from __future__ import annotations


def detect_shadow_routes(app_routes: list[str], spec_routes: set[str]) -> list[str]:
    """Return routes present in *app_routes* but absent from *spec_routes*.

    Args:
        app_routes: List of route paths registered in the ASGI app.
        spec_routes: Set of documented paths from the OpenAPI spec.

    Returns:
        List of undocumented (shadow) route paths.
    """
    shadow: list[str] = []
    for route in app_routes:
        if route not in spec_routes and (not route.startswith('/openapi')):
            shadow.append(route)
    return shadow
