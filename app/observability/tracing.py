"""Tracing with OpenTelemetry: one span per query step, per node call and per model call, carrying the mesh trace ID.

Export happens only when NEURALMESH_OTEL_ENDPOINT names an OTLP/HTTP collector. Without it the spans are created
on a no-op provider, so the code path is the same and nothing is sent. Span names follow the OpenTelemetry
conventions for generative AI as far as they are stable: `invoke_agent` style step spans are named
`mesh.<step>`, node calls `execute_tool <tool>`, model calls `chat <model>`. The convention version is pinned
here so a rename is a deliberate change. Question text and answers are never put on a span.
"""
from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Any, Iterator

from shared.config import get_settings

log = logging.getLogger("tracing")
CONVENTION_VERSION = "gen-ai-semconv 1.41 (development status), names pinned 2026-11-07"
_INITIALISED = False
_tracer: Any = None


def init_tracing(service_name: str = "neuralmesh-api") -> None:
    """Set the tracer provider. An exporter is added only when an endpoint is configured."""
    global _INITIALISED, _tracer
    if _INITIALISED:
        return
    try:
        from opentelemetry import trace
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider

        settings = get_settings()
        provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
        if settings.neuralmesh_otel_endpoint:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
            from opentelemetry.sdk.trace.export import BatchSpanProcessor

            headers = dict(h.split("=", 1) for h in settings.neuralmesh_otel_headers.split(",") if "=" in h)
            provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=settings.neuralmesh_otel_endpoint, headers=headers)))
            log.info("traces exported to %s", settings.neuralmesh_otel_endpoint)
        trace.set_tracer_provider(provider)
        _tracer = trace.get_tracer("neuralmesh", CONVENTION_VERSION)
        _INITIALISED = True
    except Exception as exc:  # noqa: BLE001 - tracing never blocks the service
        log.warning("tracing not initialised: %s", exc)


@contextmanager
def span(name: str, attributes: dict[str, Any] | None = None) -> Iterator[None]:
    """A span around one unit of work. A no-op when tracing is not initialised."""
    if _tracer is None:
        yield None
        return
    with _tracer.start_as_current_span(name) as s:
        for k, v in (attributes or {}).items():
            if v is not None:
                s.set_attribute(k, v if isinstance(v, (str, int, float, bool)) else str(v))
        yield s


def instrument_fastapi(app) -> None:
    """Instrument a FastAPI app instance (call after app creation)."""
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.instrument_app(app)
    except Exception as exc:  # noqa: BLE001
        log.warning("fastapi instrumentation skipped: %s", exc)
