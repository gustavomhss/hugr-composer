"""Pure Python primitive: FieldGenerator."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional
import uuid
from datetime import datetime

class FieldGenerator:
    """Generate realistic field values by column name and type hints."""

    def generate_instance(self, model_cls: Any) -> Any:
        """Generate an unsaved ORM instance of *model_cls* with realistic values.

        Args:
            model_cls: SQLAlchemy ORM model class (mapper object or class).

        Returns:
            Unsaved ORM model instance populated with generated data.
        """
        if hasattr(model_cls, 'class_'):
            cls = model_cls.class_
        else:
            cls = model_cls
        kwargs: dict[str, Any] = {}
        try:
            mapper = cls.__mapper__
            for col in mapper.columns:
                if col.primary_key or col.foreign_keys:
                    continue
                kwargs[col.name] = self._value_for_column(col)
        except Exception as exc:
            logger.warning('Could not inspect %s: %s', cls.__name__, exc)
        return cls(**kwargs)

    def _value_for_column(self, column: Any) -> Any:
        """Generate a realistic value for *column* by name and type.

        Args:
            column: SQLAlchemy Column object.

        Returns:
            Generated value appropriate for the column.
        """
        name = column.name.lower()
        col_type = type(column.type).__name__.lower()
        if self._is_nullable(column):
            if random.random() < 0.1:
                return None
        if 'email' in name:
            return self._email()
        if 'name' in name and 'username' not in name:
            return self._full_name()
        if 'username' in name:
            return self._username()
        if 'price' in name or 'amount' in name or 'cost' in name:
            return round(random.uniform(1.0, 999.99), 2)
        if 'url' in name or 'link' in name:
            return f'https://example.com/{self._slug()}'
        if 'phone' in name:
            return f'+1-555-{random.randint(100, 999)}-{random.randint(1000, 9999)}'
        if 'bool' in col_type or 'boolean' in name:
            return random.choice([True, False])
        if 'int' in col_type or 'integer' in col_type:
            return random.randint(1, 1000)
        if 'float' in col_type or 'numeric' in col_type:
            return round(random.uniform(0.0, 1000.0), 2)
        if 'date' in col_type:
            return self._random_date()
        if 'uuid' in col_type or 'uuid' in name:
            return str(uuid.uuid4())
        return self._text(col_type)

    def _is_nullable(self, column: Any) -> bool:
        """Return True when *column* allows NULL values.

        Args:
            column: SQLAlchemy Column object.

        Returns:
            True if column is nullable.
        """
        return getattr(column, 'nullable', True)

    def _email(self) -> str:
        """Generate a realistic-looking email address.

        Returns:
            Email string like 'alice.smith@example.com'.
        """
        first = random.choice(_FIRST_NAMES).lower()
        last = random.choice(_LAST_NAMES).lower()
        domain = random.choice(_DOMAINS)
        return f'{first}.{last}@{domain}'

    def _full_name(self) -> str:
        """Generate a realistic full name.

        Returns:
            Full name string like 'Alice Smith'.
        """
        return f'{random.choice(_FIRST_NAMES)} {random.choice(_LAST_NAMES)}'

    def _username(self) -> str:
        """Generate a unique username.

        Returns:
            Username string like 'alice_7423'.
        """
        return f'{random.choice(_FIRST_NAMES).lower()}_{random.randint(1000, 9999)}'

    def _slug(self) -> str:
        """Generate a URL-safe slug.

        Returns:
            Slug string like 'alpha-beta-42'.
        """
        return '-'.join(random.choices(_WORDS, k=2)) + f'-{random.randint(1, 99)}'

    def _text(self, col_type: str) -> str:
        """Generate generic text appropriate for the column type.

        Args:
            col_type: Lowercase SQLAlchemy type name string.

        Returns:
            Short random text string.
        """
        if 'text' in col_type:
            return ' '.join(random.choices(_WORDS, k=random.randint(5, 15)))
        length = 12
        return ''.join(random.choices(string.ascii_lowercase, k=length))

    def _random_date(self) -> str:
        """Generate a random ISO date string within a reasonable range.

        Returns:
            ISO 8601 date string like '2024-07-15'.
        """
        year = random.randint(2020, 2025)
        month = random.randint(1, 12)
        day = random.randint(1, 28)
        return f'{year}-{month:02d}-{day:02d}'
