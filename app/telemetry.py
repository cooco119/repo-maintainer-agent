import os
from opentelemetry import trace

tracer = trace.get_tracer("devin-remediator")
if os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"):
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    provider = TracerProvider(resource=Resource.create({"service.name": "devin-remediator"}))
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(
        endpoint=os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"])))
    trace.set_tracer_provider(provider)

def span(name, correlation_id):
    context = tracer.start_as_current_span(name)
    return context
