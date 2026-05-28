from __future__ import annotations
import re


class InputSanitizer:
    """HTML/XSS sanitization with optional bleach support.

    Args:
        allowed_tags: HTML tags to allow (bleach allowlist).
            Empty list strips all tags.
    """

    def __init__(self, allowed_tags: list[str] | None=None) -> None:
        """Initialise with an optional HTML allowlist.

        Args:
            allowed_tags: Tags to preserve during sanitize_html().
                Defaults to empty list (strip all tags).
        """
        self._allowed_tags: list[str] = allowed_tags or []

    def sanitize_html(self, value: str) -> str:
        """Sanitize *value* by stripping disallowed HTML tags.

        Tries bleach first (allowlist-based); falls back to
        ``html.escape`` when bleach is not installed.

        Args:
            value: Raw string that may contain HTML/script tags.

        Returns:
            Sanitized string safe for storage and display.
        """
        try:
            import bleach
            return bleach.clean(value, tags=self._allowed_tags, strip=True)
        except ImportError:
            logger.debug('bleach not installed — using html.escape fallback')
            return html.escape(value)

    def strip_tags(self, value: str) -> str:
        """Strip ALL HTML tags from *value* using a simple regex.

        For full accuracy prefer ``sanitize_html()``. This method is a
        fast fallback that does not depend on bleach.

        Args:
            value: Raw string possibly containing HTML tags.

        Returns:
            String with all ``<tag>`` sequences removed.
        """
        return re.sub('<[^>]*>', '', value)

    def escape_sql_chars(self, value: str) -> str:
        """Escape common SQL injection characters in *value*.

        Removes ``;``, single/double quotes, backslashes, and ``--``
        comment sequences. Prefer parameterised queries over this method
        for real SQL protection — this is a defence-in-depth layer only.

        Args:
            value: String to escape.

        Returns:
            String with SQL-special characters removed.
        """
        return _SQL_CHARS_RE.sub('', value)
