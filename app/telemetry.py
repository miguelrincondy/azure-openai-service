"""
Instrumentación con OpenLLMetry (Traceloop SDK).

A diferencia de OneAgent (inyección de código a nivel de proceso/registro
Docker), OpenLLMetry es una librería de Python que parchea automáticamente
el SDK de OpenAI/Azure OpenAI para emitir spans OTLP con atributos GenAI
(modelo, tokens, latencia, prompts) — sin necesidad de ningún registro
Docker privado ni credenciales de build-time. Solo requiere un endpoint
OTLP y un Access Token de Dynatrace con scopes de ingesta.
"""
import logging

from traceloop.sdk import Traceloop

from app.config import settings

logger = logging.getLogger(__name__)


def setup_telemetry() -> None:
    if not settings.dt_otlp_endpoint or not settings.dt_api_token:
        logger.warning(
            "DT_OTLP_ENDPOINT o DT_API_TOKEN no configurados; "
            "OpenLLMetry no reportará datos a Dynatrace."
        )
        return

    headers = {"Authorization": f"Api-Token {settings.dt_api_token}"}
    Traceloop.init(
        app_name=settings.service_name,
        api_endpoint=settings.dt_otlp_endpoint,
        headers=headers,
    )
    logger.info("OpenLLMetry inicializado, reportando a %s", settings.dt_otlp_endpoint)