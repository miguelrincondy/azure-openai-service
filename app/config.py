"""
Configuración del servicio, leída desde variables de entorno.

AUTH_MODE controla cómo se autentica contra Azure OpenAI:
  - "api_key"           -> usa AZURE_OPENAI_API_KEY
  - "managed_identity"  -> usa DefaultAzureCredential (recomendado en Azure Container Apps)

La observabilidad la aporta OpenLLMetry (Traceloop SDK), que instrumenta
automáticamente el SDK de OpenAI/Azure OpenAI y exporta spans OTLP hacia
Dynatrace. Ver README.md, sección "Instrumentación con OpenLLMetry".
"""
import os


class Settings:
    # --- Azure OpenAI ---
    azure_openai_endpoint: str = os.getenv("AZURE_OPENAI_ENDPOINT", "")
    azure_openai_deployment: str = os.getenv("AZURE_OPENAI_DEPLOYMENT", "")
    azure_openai_api_version: str = os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-21")

    auth_mode: str = os.getenv("AUTH_MODE", "api_key")  # api_key | managed_identity
    azure_openai_api_key: str = os.getenv("AZURE_OPENAI_API_KEY", "")

    # --- Observabilidad (OpenLLMetry / Traceloop) ---
    # Endpoint OTLP de tu ambiente Dynatrace, formato: https://<env>.<dominio>/api/v2/otlp
    dt_otlp_endpoint: str = os.getenv("DT_OTLP_ENDPOINT", "")
    # Access Token de Dynatrace con scopes: openTelemetryTrace.ingest, metrics.ingest, logs.ingest
    dt_api_token: str = os.getenv("DT_API_TOKEN", "")

    # --- App ---
    service_name: str = os.getenv("SERVICE_NAME", "azure-openai-service")
    service_version: str = os.getenv("SERVICE_VERSION", "0.1.0")
    environment: str = os.getenv("DEPLOY_ENVIRONMENT", "dev")
    app_port: int = int(os.getenv("APP_PORT", "8000"))


settings = Settings()