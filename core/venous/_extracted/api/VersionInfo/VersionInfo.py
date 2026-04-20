from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class VersionInfo:
    """Immutable descriptor for a single API version.

    Attributes:
        name: Version label, e.g. "v1".
        is_deprecated: True when this version is scheduled for removal.
        sunset_date: Calendar date after which the version is removed.
        changelog_url: Link to the version's changelog entry.
    """
    name: str
    is_deprecated: bool = False
    sunset_date: date | None = None
    changelog_url: str = ''

    @property
    def sunset_header(self) -> str | None:
        """Return an RFC 7231-formatted Sunset header value, or None.

        Returns:
            Formatted date string or None if sunset_date is unset.
        """
        if self.sunset_date is None:
            return None
        import calendar
        d = self.sunset_date
        wd = calendar.day_abbr[d.weekday()]
        mon = calendar.month_abbr[d.month]
        return f'{wd}, {d.day:02d} {mon} {d.year} 00:00:00 GMT'
