"""
Wrapper simple sobre el SDK de Azure OpenAI.

Sin instrumentación manual: OneAgent instrumenta automáticamente el SDK de
OpenAI (feature "Python OpenAI") y el framework web (feature "Python FastAPI"),
capturando modelo, tokens y latencia sin cambios de código. Ver README.md.
"""
import logging

from openai import AzureOpenAI

from app.config import settings

logger = logging.getLogger(__name__)


def _build_client() -> AzureOpenAI:
    if settings.auth_mode == "managed_identity":
        from azure.identity import DefaultAzureCredential, get_bearer_token_provider

        token_provider = get_bearer_token_provider(
            DefaultAzureCredential(),
            "https://cognitiveservices.azure.com/.default",
        )
        return AzureOpenAI(
            azure_endpoint=settings.azure_openai_endpoint,
            azure_ad_token_provider=token_provider,
            api_version=settings.azure_openai_api_version,
        )

    # Modo por defecto: API Key
    return AzureOpenAI(
        azure_endpoint=settings.azure_openai_endpoint,
        api_key=settings.azure_openai_api_key,
        api_version=settings.azure_openai_api_version,
    )


_client: AzureOpenAI | None = None


def get_client() -> AzureOpenAI:
    global _client
    if _client is None:
        _client = _build_client()
    return _client


def chat_completion(prompt: str, max_tokens: int = 256) -> dict:
    """Llama al deployment configurado y devuelve texto + uso de tokens.

    OneAgent crea automáticamente un span hijo del entry-point HTTP con los
    atributos gen_ai.provider, gen_ai.model, gen_ai.usage.input_tokens /
    output_tokens — visibles en AI Observability > Explorer y en Distributed
    Tracing, sin que este código necesite reportarlos.
    """
    client = get_client()

    try:
        response = client.chat.completions.create(
            model=settings.azure_openai_deployment,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
        )
    except Exception:
        logger.exception("Error llamando a Azure OpenAI")
        raise

    usage = response.usage
    return {
        "text": response.choices[0].message.content,
        "usage": {
            "prompt_tokens": usage.prompt_tokens,
            "completion_tokens": usage.completion_tokens,
            "total_tokens": usage.total_tokens,
        },
    }
