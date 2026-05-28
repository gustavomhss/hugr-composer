from __future__ import annotations
from enum import Enum


class TemplateName(str, Enum):
    """Built-in transactional template identifiers.

    Values are the on-disk filename stems (without extension).
    The renderer expects three sibling files per template under
    ``app/email/templates/{locale}/``:

        * ``{name}.subject.txt`` — plaintext subject line
        * ``{name}.html``       — HTML body (inline CSS)
        * ``{name}.txt``        — plaintext body
    """
    WELCOME = 'welcome'
    PASSWORD_RESET = 'password_reset'
    EMAIL_VERIFICATION = 'email_verification'
    RECEIPT = 'receipt'
