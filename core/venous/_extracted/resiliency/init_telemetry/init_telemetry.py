from __future__ import annotations


def init_telemetry() -> None:
    """Bootstrap TracerProvider, MeterProvider, and LoggerProvider.

    Reads configuration from ``app.core.config.settings``.  When
    ``OTEL_ENABLED`` is ``False`` this function is a no-op — no SDK
    packages are imported.
    """
    from app.core.config import settings
    if not settings.OTEL_ENABLED:
        logger.debug('OTEL disabled — skipping telemetry bootstrap')
        return
    _init_tracer_provider(settings)
    _init_meter_provider(settings)
    _init_logger_provider(settings)
    logger.info("OpenTelemetry initialised for service '%s'", settings.OTEL_SERVICE_NAME)
