from __future__ import annotations


def get_tracer(name: str='app'):
    """Return a tracer from the global TracerProvider.

    When OTEL is disabled returns a no-op tracer so callers need
    not check the enabled flag themselves.

    Args:
        name: Instrumentation scope name (typically ``__name__``).

    Returns:
        An OpenTelemetry Tracer instance.
    """
    try:
        from opentelemetry import trace
        return trace.get_tracer(name)
    except ImportError:
        from opentelemetry.trace import NoOpTracer
        return NoOpTracer()
