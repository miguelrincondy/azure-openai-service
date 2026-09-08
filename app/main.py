import logging

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from app.config import settings
from app.openai_client import chat_completion
from app.telemetry import setup_telemetry

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

setup_telemetry()

app = FastAPI(title="Azure OpenAI Service", version=settings.service_version)


class ChatRequest(BaseModel):
    prompt: str
    max_tokens: int = 256


class ChatResponse(BaseModel):
    text: str
    usage: dict
    duration_ms: float


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": settings.service_name, "env": settings.environment}


@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest) -> ChatResponse:
    if not settings.azure_openai_endpoint or not settings.azure_openai_deployment:
        raise HTTPException(
            status_code=500,
            detail="AZURE_OPENAI_ENDPOINT y AZURE_OPENAI_DEPLOYMENT deben estar configurados",
        )
    try:
        result = chat_completion(request.prompt, request.max_tokens)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Fallo en /chat")
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return ChatResponse(**result)