import logging
import os
from opentelemetry import trace
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from app.config import settings

tracer = trace.get_tracer('rag.platform')


def configure_langsmith():
    """Expose Pydantic-loaded LangSmith settings to LangChain's tracing SDK."""
    values = {
        'LANGSMITH_TRACING': str(settings.LANGSMITH_TRACING).lower(),
        'LANGSMITH_ENDPOINT': settings.LANGSMITH_ENDPOINT,
        'LANGSMITH_API_KEY': settings.LANGSMITH_API_KEY,
        'LANGSMITH_PROJECT': settings.LANGSMITH_PROJECT,
        # Agent addressing and project/thread addressing are mutually exclusive.
        'LANGSMITH_AGENT_ID': '',
        'LANGSMITH_AGENT_ENVIRONMENT': '',
    }
    for key, value in values.items():
        if value:
            os.environ[key] = value
        else:
            os.environ.pop(key, None)


def configure(app):
    configure_langsmith()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s %(message)s')
    # HTTP debug logs can contain endpoints or provider response bodies.
    logging.getLogger('httpx').setLevel(logging.WARNING)
    logging.getLogger('openai').setLevel(logging.WARNING)
    if settings.OTEL_EXPORTER_OTLP_ENDPOINT:
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        provider = TracerProvider(resource=Resource.create({'service.name':'rag-platform'}))
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(
            endpoint=settings.OTEL_EXPORTER_OTLP_ENDPOINT.rstrip('/') + '/v1/traces')))
        trace.set_tracer_provider(provider)
    FastAPIInstrumentor.instrument_app(app, excluded_urls='/api/health,/api/ready')
