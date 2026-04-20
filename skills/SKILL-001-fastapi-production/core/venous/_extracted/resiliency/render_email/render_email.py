from __future__ import annotations
from typing import Any


def render_email(name: TemplateName, context: dict[str, Any], locale: str='en') -> RenderedEmail:
    """Render a template triple into a ``RenderedEmail``.

    Args:
        name: Template identifier.
        context: Values to inject into the Jinja2 templates.
        locale: Preferred locale; falls back to ``"en"`` automatically.

    Returns:
        A ``RenderedEmail`` with non-empty ``subject``, ``html``, and ``text``.

    Raises:
        MissingContextError: If required context keys are missing.
        TemplateNotFound: If no locale has the template.
    """
    _validate_context(name, context)
    resolved = _resolve_locale(name, locale)
    env = _build_env(resolved)
    subject = env.get_template(f'{name.value}.subject.txt').render(**context).strip()
    html = env.get_template(f'{name.value}.html').render(**context)
    text = env.get_template(f'{name.value}.txt').render(**context)
    return RenderedEmail(subject=subject, html=html, text=text)
