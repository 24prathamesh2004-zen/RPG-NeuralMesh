"""OpenTelemetry + Arize Phoenix tracing initialisation.

Cloud Phoenix (ACA-hosted):
- Collector endpoint via PHOENIX_COLLECTOR_ENDPOINT
  (e.g. https://zaf-phoenix.bravesky-d9f9eeb7.eastus2.azurecontainerapps.io/v1/traces)
- Auth: Bearer token from ARIZE_PHOENIX_API_KEY

Local fallback: http://<phoenix_host>:<phoenix_port>/v1/traces (no auth).

Uses the OTLP/HTTP exporter + openinference instrumentors so LangChain /
LangGraph / OpenAI calls appear as proper spans in Phoenix. All imports are
lazy so a missing observability package never blocks app startup.
"""
from __future__ import annotations

import logging

from shared.config import get_settings

log = logging.getLogger("tracing")

_INITIALISED = False


def init_tracing(service_name: str = "__APP_NAME__-backend") -> None:
    """Configure the OTel TracerProvider and instrument FastAPI + LangChain + OpenAI.

    ``service_name`` identifies which process emitted a span (the FastAPI API
    vs. the Temporal worker) — both write to the same Phoenix project, but this
    lets you tell the two execution paths apart in a trace.
    """
    global _INITIALISED
    if _INITIALISED:
        return

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        settings = get_settings()

        if settings.phoenix_collector_endpoint:
            endpoint = settings.phoenix_collector_endpoint.rstrip("/")
            if not endpoint.endswith("/v1/traces"):
                endpoint = f"{endpoint}/v1/traces"
        else:
            endpoint = f"http://{settings.phoenix_host}:{settings.phoenix_port}/v1/traces"

        headers = {}
        if settings.arize_phoenix_api_key:
            headers["Authorization"] = f"Bearer {settings.arize_phoenix_api_key}"

        provider = TracerProvider(
            resource=Resource.create(
                {
                    "service.name": service_name,
                    "openinference.project.name": settings.phoenix_project_name,
                }
            )
        )
        provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint, headers=headers))
        )
        trace.set_tracer_provider(provider)

        # ── Instrumentors (each optional) ──────────────────────────────────────
        try:
            from openinference.instrumentation.langchain import LangChainInstrumentor

            LangChainInstrumentor().instrument(tracer_provider=provider)
            log.info("LangChain instrumented (openinference)")
        except Exception as exc:  # noqa: BLE001
            log.warning("langchain instrumentation skipped: %s", exc)

        try:
            from openinference.instrumentation.openai import OpenAIInstrumentor

            OpenAIInstrumentor().instrument(tracer_provider=provider)
            log.info("OpenAI instrumented (openinference)")
        except Exception as exc:  # noqa: BLE001
            log.warning("openai instrumentation skipped: %s", exc)

        log.info("OTel TracerProvider initialised -> %s (project: %s)",
                 endpoint, settings.phoenix_project_name)
        _INITIALISED = True
    except Exception as exc:  # noqa: BLE001
        log.warning("init_tracing failed (continuing without tracing): %s", exc)


def instrument_fastapi(app) -> None:
    """Instrument a FastAPI app instance (call after app creation)."""
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.instrument_app(app)
        log.info("FastAPI instrumented")
    except Exception as exc:  # noqa: BLE001
        log.warning("fastapi instrumentation skipped: %s", exc)
