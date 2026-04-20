from __future__ import annotations
from pathlib import Path


def generate_bola_tests(model_name: str, route_prefix: str, output_path: str, owner_field: str='user_id') -> str:
    """Generate a pytest test file covering BOLA attack scenarios.

    Args:
        model_name: SQLAlchemy model name (e.g. 'Order').
        route_prefix: API route prefix (e.g. '/api/v1/orders').
        output_path: File path to write the generated test file.
        owner_field: Column that stores the owner user_id.

    Returns:
        Absolute path of the generated test file.
    """
    content = _render_test_template(model_name, route_prefix, owner_field)
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return str(path.resolve())
