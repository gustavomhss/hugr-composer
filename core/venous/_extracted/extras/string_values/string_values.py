from __future__ import annotations
from typing import Any


def string_values() -> list[Any]:
    """Return adversarial string values (empty, huge, SQL, XSS, unicode)."""
    sql_payloads = ["' OR '1'='1", "'; DROP TABLE users; --", '1; SELECT * FROM information_schema.tables']
    xss_vectors = ['<script>alert(1)</script>', '"><img src=x onerror=alert(1)>', 'javascript:alert(1)']
    unicode_edge = ['\x00', '\uffff', '\u202e', 'A' * 1048576, '']
    control_chars = ['\r\n', '\n' * 3, '\t' * 3]
    null_and_type_confuse: list[Any] = [None, 0, False, [], {}]
    return sql_payloads + xss_vectors + unicode_edge + control_chars + null_and_type_confuse
