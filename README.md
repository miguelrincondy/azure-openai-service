# azure-openai-service

**azure-openai-service** es un servicio backend en Python (FastAPI) que expone un endpoint HTTP para consumir modelos de **Azure OpenAI**. El proyecto sirve como caso de validación de instrumentación: la observabilidad completa —trazas distribuidas, métricas de consumo de tokens y latencia— la aporta **Dynatrace OneAgent** mediante inyección de código a nivel de proceso (zero-code), sin necesidad de SDKs de instrumentación ni cambios en el código de la aplicación.

## Estructura

```
app/
  main.py           # FastAPI: endpoints /health y /chat
  openai_client.py  # cliente Azure OpenAI (API Key o Managed Identity), sin instrumentación manual
  config.py         # configuración vía variables de entorno
Dockerfile          # incluye la inyección del code module de OneAgent (dominio parametrizado por ARG)
requirements.txt
.env.example
.gitignore
.dockerignore
```

## Instrumentación con OneAgent (zero-code)

Según la [guía oficial](https://docs.dynatrace.com/docs/observe/dynatrace-for-ai-observability/get-started/oneagent), OneAgent captura automáticamente atributos GenAI (modelo, tokens, latencia, y opcionalmente el prompt) sin ningún wrapper de SDK.

### El dominio de Dynatrace es un build-arg, no está hardcodeado

El `Dockerfile` declara `ARG DT_ENVIRONMENT_URL` y lo usa en:

```dockerfile
ARG DT_ENVIRONMENT_URL
COPY --from=${DT_ENVIRONMENT_URL}/linux/oneagent-codemodules:python / /
ENV LD_PRELOAD=/opt/dynatrace/oneagent/agent/lib64/liboneagentproc.so
```

Esto evita tener que editar y commitear el Dockerfile por cada entorno Dynatrace — el valor se pasa en el momento del build (ver sección de despliegue).

`<DT_ENVIRONMENT_URL>` es uno de:
- SaaS: `<tu-environment-id>.live.dynatrace.com`
- ActiveGate: `<activegate-address>:9999`

### Versión mínima requerida del SDK

Según la tabla **"Generative AI Application frameworks"** de Dynatrace (Technology support), la instrumentación automática de OpenAI/Azure OpenAI requiere:

| Framework | Versión mínima |
|---|---|
| `openai` (Python SDK) | **1.54.0+** (captura de prompts soportada desde OneAgent 1.335) |

`requirements.txt` ya está fijado a `openai>=1.54.0`.

### Habilitar las features de OneAgent (en la UI de Dynatrace)

En **Settings** → **Collect and capture** → **General monitoring settings** → **OneAgent features**, filtra por "Python" y habilita:

| Feature | Obligatoria |
|---|---|
| Python OpenAI | Sí — instrumenta el SDK y habilita el monitoreo |
| Python FastAPI | Sí — crea el span de entrada HTTP donde anida la llamada a OpenAI |
| Python OpenAI prompt capture | Opcional — captura el texto del prompt y la respuesta |

Después de habilitarlas, **reinicia la aplicación** (las features se aplican al arrancar el proceso).

### Enviar tráfico y observar

```bash
curl -X POST https://<fqdn-del-container-app>/chat \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Explica qué es la observabilidad en una frase"}'
```

Luego en Dynatrace:
- **AI Observability → Explorer**: el servicio aparece como AI service tras la primera request instrumentada, con conteo de requests y uso de tokens agregado.
- **Distributed Tracing**: el span de entrada HTTP (FastAPI) contiene como hijo el span de la llamada a Azure OpenAI, con `gen_ai.provider`, `gen_ai.model`, `gen_ai.usage.input_tokens` / `output_tokens`.

## 1. Ejecutar localmente (opcional, sin OneAgent)

Si en algún momento tienes Python disponible localmente y quieres probar rápido sin instrumentación:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # completa AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_DEPLOYMENT, AZURE_OPENAI_API_KEY (nunca subas este .env — ya está en .gitignore)
export $(grep -v '^#' .env | xargs)
uvicorn app.main:app --reload --port 8000
```

```bash
curl http://localhost:8000/health
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Explica qué es la observabilidad en una frase", "max_tokens": 100}'
```

## 2. Construir la imagen (sin Docker local, vía ACR Task)

Todo esto se ejecuta desde **Azure Cloud Shell** (portal.azure.com → icono `>_`), sin instalar nada.

```bash
RG=rg-azure-openai-demo
LOCATION=eastus2
ACR_NAME=acraoservicedemo   # único globalmente
REPO_URL=https://github.com/<tu-usuario>/azure-openai-service.git

# 1. Resource group + ACR
az group create -n $RG -l $LOCATION
az acr create -n $ACR_NAME -g $RG --sku Basic

# 2. Crear la ACR Task apuntando al repo (el dominio de Dynatrace va como --arg)
az acr task create \
  --registry $ACR_NAME --name build-oneagent \
  --image azure-openai-service:{{.Run.ID}} \
  --context "$REPO_URL#main" --file Dockerfile \
  --arg DT_ENVIRONMENT_URL=<tu-environment-id>.live.dynatrace.com \
  --git-access-token <tu-PAT-de-GitHub>

# 3. Registrar la credencial del registro de Dynatrace en la Task
az acr task credential add \
  --name build-oneagent --registry $ACR_NAME \
  --login-server <tu-environment-id>.live.dynatrace.com \
  --username <DT_ENVIRONMENT_ID> --password <tu-PaaS-Token>

# 4. Ejecutar el build remoto (push automático al ACR al terminar)
az acr task run --registry $ACR_NAME --name build-oneagent
```

Verifica que la imagen quedó:

```bash
az acr repository show-tags --name $ACR_NAME --repository azure-openai-service
```

> Si en algún momento sí tienes Docker disponible, la alternativa clásica es `docker login <DT_ENVIRONMENT_URL> -u <DT_ENVIRONMENT_ID>` + `docker build --build-arg DT_ENVIRONMENT_URL=<...> -t ... .` + `docker push` — el `ARG` del Dockerfile funciona igual en ambos flujos.

## 3. Desplegar en Azure Container Apps

```bash
CAE_NAME=cae-azure-openai-demo
APP_NAME=azure-openai-service

# Variables reales solo en la sesión de shell, nunca en archivos
export AZURE_OPENAI_ENDPOINT="https://<tu-recurso>.openai.azure.com"
export AZURE_OPENAI_DEPLOYMENT="<tu-deployment>"
export AZURE_OPENAI_KEY="<tu-api-key>"

# Entorno de Container Apps
az containerapp env create -n $CAE_NAME -g $RG -l $LOCATION

# Deploy (modo API Key para empezar)
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
  --secrets azure-openai-key=$AZURE_OPENAI_KEY \
  --env-vars AZURE_OPENAI_API_KEY=secretref:azure-openai-key
```

Obtén la URL pública:

```bash
az containerapp show -n $APP_NAME -g $RG --query properties.configuration.ingress.fqdn -o tsv
```

### Sobre credenciales de Azure OpenAI (pendiente de decidir)

Controlado por `AUTH_MODE`:

- **`api_key`** (por defecto): simple para pruebas, la key va como *secret* de Container Apps (como en el ejemplo de arriba).
- **`managed_identity`**: usa `DefaultAzureCredential`, sin ninguna key en el servicio. Requiere:
  1. `az containerapp identity assign --system-assigned -n $APP_NAME -g $RG`
  2. Asignar el rol `Cognitive Services OpenAI User` sobre el recurso de Azure OpenAI a esa identidad.
  3. `AUTH_MODE=managed_identity` (y quitar `AZURE_OPENAI_API_KEY`).

## Notas

- `/health` no llama a Azure OpenAI, solo confirma que el proceso está arriba (útil para probes de Container Apps).
- El Dockerfile corre el proceso como root: OneAgent inyectado vía `LD_PRELOAD` necesita escribir en `/opt/dynatrace`, así que se dejó así para evitar fallos de permisos. Si quieres correr como usuario no-root, habría que ajustar los permisos de `/opt/dynatrace` explícitamente.
- Requisitos del lado Dynatrace: SaaS con licencia Dynatrace Platform Subscription (DPS), y una versión de OneAgent que soporte el SDK de OpenAI (ver [support matrix](https://docs.dynatrace.com/docs/ingest-from/technology-support/oneagent-platform-and-capability-support-matrix)).