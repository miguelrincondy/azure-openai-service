# syntax=docker/dockerfile:1
FROM python:3.12-slim

WORKDIR /app

# ---------------------------------------------------------------------------
# OneAgent (application-only monitoring, sin Kubernetes/Operator): copia el
# code module de Python directamente desde el registro de tu entorno Dynatrace.
#
# ANTES DE CONSTRUIR, autentícate contra ese registro:
#   docker login <DT_ENVIRONMENT_URL> -u <DT_ENVIRONMENT_ID>
#   (te pedirá tu PaaS Token como password)
#
# Reemplaza <DT_ENVIRONMENT_URL> abajo por uno de:
#   - SaaS:        <tu-environment-id>.live.dynatrace.com
#   - ActiveGate:  <activegate-address>:9999
#
# IMPORTANTE: si construyes con "az acr build" (build remoto en ACR), ese
# entorno NO tiene tus credenciales locales de Dynatrace y la línea de abajo
# fallará. Construye la imagen localmente con `docker build` y luego haz
# `docker push` a tu ACR. Ver README.md, sección "Instrumentación con OneAgent".
# ---------------------------------------------------------------------------
COPY --from=<DT_ENVIRONMENT_URL>/linux/oneagent-codemodules:python / /
ENV LD_PRELOAD=/opt/dynatrace/oneagent/agent/lib64/liboneagentproc.so

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
