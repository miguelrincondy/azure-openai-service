# azure-openai-service

**azure-openai-service** es un servicio backend en Python (FastAPI) que expone un endpoint HTTP para consumir modelos de **Azure OpenAI**. El proyecto sirve como caso de validación de instrumentación: la observabilidad completa —trazas distribuidas, métricas de consumo de tokens y latencia— la aporta **OpenLLMetry (Traceloop SDK)**, una capa de auto-instrumentación sobre OpenTelemetry especializada en aplicaciones GenAI.

## Estructura

```
app/
  main.py           # FastAPI: endpoints /health y /chat
  openai_client.py  # cliente Azure OpenAI (API Key o Managed Identity)
  telemetry.py       # inicialización de OpenLLMetry (Traceloop)
  config.py          # configuración vía variables de entorno
Dockerfile
requirements.txt
.env.example
.gitignore
.dockerignore
```

## Instrumentación con OpenLLMetry (Traceloop)

A diferencia de Dynatrace OneAgent (que requiere inyectar un code module desde el registro Docker de tu entorno, con `docker login` y credenciales de build-time), **OpenLLMetry es una librería de Python** (`traceloop-sdk`) que se instala como cualquier dependencia y parchea automáticamente el SDK de OpenAI/Azure OpenAI en tiempo de ejecución. No hay ningún registro Docker que resolver, ni credenciales en el build de la imagen — solo un endpoint OTLP y un token de ingesta.

### 1. Generar el Access Token en Dynatrace

En Dynatrace: **Access Tokens** (Ctrl/Cmd+K → buscar "Access Tokens") → **Generate new token**. Selecciona estos scopes:

- `openTelemetryTrace.ingest`
- `metrics.ingest`
- `logs.ingest`

Copia el token generado — solo se muestra una vez.

### 2. Configurar el endpoint OTLP

El endpoint sigue el patrón `https://<tu-environment-id>.<tu-dominio>/api/v2/otlp`. Para tu ambiente:

```
DT_OTLP_ENDPOINT=https://yaj06303.sprint.dynatracelabs.com/api/v2/otlp
DT_API_TOKEN=<el-token-generado-en-el-paso-1>
```

Estos van como variables de entorno del contenedor (nunca en un archivo del repo — ver sección de despliegue).

### 3. Cómo funciona en el código

`app/telemetry.py` inicializa Traceloop al arrancar la app:

```python
from traceloop.sdk import Traceloop

Traceloop.init(
    app_name=settings.service_name,
    api_endpoint=settings.dt_otlp_endpoint,
    headers={"Authorization": f"Api-Token {settings.dt_api_token}"},
)
```

A partir de ahí, cada llamada a `client.chat.completions.create(...)` en `openai_client.py` queda automáticamente instrumentada: modelo, tokens de prompt/completion, latencia y (opcionalmente) el contenido del prompt viajan como atributos del span, sin código adicional de nuestra parte.

### 4. Enviar tráfico y observar

```bash
curl -X POST https://<fqdn-del-container-app>/chat \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Explica qué es la observabilidad en una frase"}'
```

En Dynatrace: **Distributed Tracing** → busca el servicio por su `app_name` (el mismo valor de `SERVICE_NAME`). El span de la llamada a Azure OpenAI aparece con los atributos GenAI estándar (`gen_ai.*`).

## 1. Ejecutar localmente (opcional)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # completa los valores reales; .env ya está en .gitignore
export $(grep -v '^#' .env | xargs)
uvicorn app.main:app --reload --port 8000
```

```bash
curl http://localhost:8000/health
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Explica qué es la observabilidad en una frase", "max_tokens": 100}'
```

## 2. Construir la imagen

Sin OneAgent, el Dockerfile ya no necesita ningún build-arg ni login especial — cualquier método de build sirve, incluyendo `az acr build` (build remoto ad-hoc, mucho más simple que la ACR Task que usábamos antes):

```bash
az acr build --registry acrmrincon --image azure-openai-service:latest .
```

(O `docker build` local si tienes Docker disponible.)

## 3. Desplegar en Azure Container Apps

```bash
RG=rg-mrincon-azure-openai-demo
LOCATION=eastus2
ACR_NAME=acrmrincon
CAE_NAME=cae-azure-openai-demo
APP_NAME=azure-openai-service

az containerapp env create -n $CAE_NAME -g $RG -l $LOCATION

# Variables reales solo en la sesión de shell, nunca en archivos
export AZURE_OPENAI_ENDPOINT="https://<tu-recurso>.openai.azure.com"
export AZURE_OPENAI_DEPLOYMENT="<tu-deployment>"
export AZURE_OPENAI_KEY="<tu-api-key>"
export DT_OTLP_ENDPOINT="https://yaj06303.sprint.dynatracelabs.com/api/v2/otlp"
export DT_API_TOKEN="<tu-access-token-con-scopes-de-ingesta>"

az containerapp create \
  --name $APP_NAME \
  --resource-group $RG \
  --environment $CAE_NAME \
  --image "$ACR_NAME.azurecr.io/azure-openai-service:latest" \
  --registry-server "$ACR_NAME.azurecr.io" \
  --target-port 8000 \
  --ingress external \
  --env-vars \
      AZURE_OPENAI_ENDPOINT=$AZURE_OPENAI_ENDPOINT \
      AZURE_OPENAI_DEPLOYMENT=$AZURE_OPENAI_DEPLOYMENT \
      AUTH_MODE=api_key \
      DT_OTLP_ENDPOINT=$DT_OTLP_ENDPOINT \
  --secrets azure-openai-key=$AZURE_OPENAI_KEY dt-api-token=$DT_API_TOKEN \
  --env-vars AZURE_OPENAI_API_KEY=secretref:azure-openai-key DT_API_TOKEN=secretref:dt-api-token
```

Obtén la URL pública:

```bash
az containerapp show -n $APP_NAME -g $RG --query properties.configuration.ingress.fqdn -o tsv
```

### Sobre credenciales de Azure OpenAI (pendiente de decidir)

Controlado por `AUTH_MODE`:

- **`api_key`** (por defecto): simple para pruebas, la key va como *secret* de Container Apps.
- **`managed_identity`**: usa `DefaultAzureCredential`, sin ninguna key en el servicio. Requiere:
  1. `az containerapp identity assign --system-assigned -n $APP_NAME -g $RG`
  2. Asignar el rol `Cognitive Services OpenAI User` sobre el recurso de Azure OpenAI a esa identidad.
  3. `AUTH_MODE=managed_identity` (y quitar `AZURE_OPENAI_API_KEY`).

## Notas

- `/health` no llama a Azure OpenAI ni depende de Dynatrace — solo confirma que el proceso está arriba.
- Dynatrace solo acepta métricas OTLP en formato **delta**; si en algún momento agregas métricas custom, recuerda `OTEL_EXPORTER_OTLP_METRICS_TEMPORALITY_PREFERENCE=DELTA`.
- Si `DT_OTLP_ENDPOINT` o `DT_API_TOKEN` no están configurados, el servicio sigue funcionando normalmente (llama a Azure OpenAI igual) — simplemente no reporta datos a Dynatrace.