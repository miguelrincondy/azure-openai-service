# azure-openai-service

**azure-openai-service** es un servicio backend en Python (FastAPI) que expone un endpoint HTTP para consumir modelos de **Azure OpenAI**. El proyecto sirve como caso de validación de instrumentación: la observabilidad completa —trazas distribuidas, métricas de consumo de tokens y latencia— la aporta **Dynatrace OneAgent** mediante inyección de código a nivel de proceso (zero-code), sin necesidad de SDKs de instrumentación ni cambios en el código de la aplicación.

## Estructura

```
app/
  main.py           # FastAPI: endpoints /health y /chat
  openai_client.py  # cliente Azure OpenAI (API Key o Managed Identity), sin instrumentación manual
  config.py         # configuración vía variables de entorno
Dockerfile          # incluye la inyección del code module de OneAgent
requirements.txt
.env.example
```

## Instrumentación con OneAgent (zero-code)

Según la [guía oficial](https://docs.dynatrace.com/docs/observe/dynatrace-for-ai-observability/get-started/oneagent), OneAgent captura automáticamente atributos GenAI (modelo, tokens, latencia, y opcionalmente el prompt) sin ningún wrapper de SDK. Esto requiere tres cosas:

### 1. Instrumentar el contenedor (build-time)

Como Azure Container Apps corre sobre Docker sin Kubernetes/Operator, se usa el modelo de **"application-only monitoring"**: el code module de OneAgent se copia dentro de la imagen en tiempo de build.

Antes de construir la imagen, autentícate contra el registro de tu entorno Dynatrace:

```bash
docker login <DT_ENVIRONMENT_URL> -u <DT_ENVIRONMENT_ID>
# password = tu PaaS Token
```

Donde `<DT_ENVIRONMENT_URL>` es:
- SaaS: `<tu-environment-id>.live.dynatrace.com`
- ActiveGate: `<activegate-address>:9999`

En el `Dockerfile` ya está la línea (reemplaza el placeholder antes de construir):

```dockerfile
COPY --from=<DT_ENVIRONMENT_URL>/linux/oneagent-codemodules:python / /
ENV LD_PRELOAD=/opt/dynatrace/oneagent/agent/lib64/liboneagentproc.so
```

> ⚠️ **Importante**: si construyes con `az acr build` (build remoto en ACR), ese entorno no tiene tus credenciales locales de Dynatrace y el `COPY --from` fallará. Construye la imagen **localmente** con `docker build` y luego haz `docker push` a tu ACR (ver sección de despliegue abajo).

### Versión mínima requerida del SDK

Según la tabla **"Generative AI Application frameworks"** de Dynatrace (Technology support), la instrumentación automática de OpenAI/Azure OpenAI requiere:

| Framework | Versión mínima |
|---|---|
| `openai` (Python SDK) | **1.54.0+** (captura de prompts soportada desde OneAgent 1.335) |

`requirements.txt` ya está fijado a `openai>=1.54.0`. Si además quisieras probar contra Amazon Bedrock en vez de Azure OpenAI (para este laboratorio es indistinto el proveedor cloud), la versión mínima soportada es `boto3`/`botocore` con **Amazon Bedrock Runtime 1.14+**.

### 2. Habilitar las features de OneAgent (en la UI de Dynatrace)

En **Settings** → **Collect and capture** → **General monitoring settings** → **OneAgent features**, filtra por "Python" y habilita:

| Feature | Obligatoria |
|---|---|
| Python OpenAI | Sí — instrumenta el SDK y habilita el monitoreo |
| Python FastAPI | Sí — crea el span de entrada HTTP donde anida la llamada a OpenAI |
| Python OpenAI prompt capture | Opcional — captura el texto del prompt y la respuesta |

Después de habilitarlas, **reinicia la aplicación** (las features se aplican al arrancar el proceso).

### 3. Enviar tráfico y observar

```bash
curl -X POST http://<tu-servicio>/chat \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Explica qué es la observabilidad en una frase"}'
```

Luego en Dynatrace:
- **AI Observability → Explorer**: el servicio aparece como AI service tras la primera request instrumentada, con conteo de requests y uso de tokens agregado.
- **Distributed Tracing**: el span de entrada HTTP (FastAPI) contiene como hijo el span de la llamada a Azure OpenAI, con `gen_ai.provider`, `gen_ai.model`, `gen_ai.usage.input_tokens` / `output_tokens`.

### Reportar a otro ambiente Dynatrace (opcional)

Si ya horneaste la imagen para un ambiente y quieres reportar a otro sin reconstruir (OneAgent 1.139+), obtén los datos de conexión:

```bash
curl "https://<environmentID>.live.dynatrace.com/api/v1/deployment/installer/agent/connectioninfo?Api-Token=<token>"
```

Y pasa el resultado como variables de entorno del contenedor: `DT_TENANT`, `DT_TENANTTOKEN`, `DT_CONNECTION_POINT` (ver `.env.example`).

## 1. Ejecutar localmente (sin Docker, sin OneAgent)

Para desarrollo rápido, sin instrumentación (esta ruta no pasa por OneAgent):

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # completa AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_DEPLOYMENT, AZURE_OPENAI_API_KEY
export $(grep -v '^#' .env | xargs)
uvicorn app.main:app --reload --port 8000
```

```bash
curl http://localhost:8000/health

curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Explica qué es la observabilidad en una frase", "max_tokens": 100}'
```

## 2. Construir la imagen (con OneAgent)

```bash
docker login <DT_ENVIRONMENT_URL> -u <DT_ENVIRONMENT_ID>   # una sola vez
docker build -t azure-openai-service:latest .
docker run --rm -p 8000:8000 --env-file .env azure-openai-service:latest
```

## 3. Desplegar en Azure Container Apps

```bash
RG=rg-azure-openai-demo
LOCATION=eastus2
ACR_NAME=acraoservicedemo   # debe ser único globalmente
CAE_NAME=cae-azure-openai-demo
APP_NAME=azure-openai-service

# 1. Resource group + Azure Container Registry
az group create -n $RG -l $LOCATION
az acr create -n $ACR_NAME -g $RG --sku Basic

# 2. Build LOCAL (no "az acr build" — ver nota sobre credenciales de OneAgent arriba)
docker login <DT_ENVIRONMENT_URL> -u <DT_ENVIRONMENT_ID>
docker build -t "$ACR_NAME.azurecr.io/azure-openai-service:latest" .
az acr login -n $ACR_NAME
docker push "$ACR_NAME.azurecr.io/azure-openai-service:latest"

# 3. Entorno de Container Apps
az containerapp env create -n $CAE_NAME -g $RG -l $LOCATION

# 4. Deploy del Container App (modo API Key para empezar)
az containerapp create \
  --name $APP_NAME \
  --resource-group $RG \
  --environment $CAE_NAME \
  --image "$ACR_NAME.azurecr.io/azure-openai-service:latest" \
  --registry-server "$ACR_NAME.azurecr.io" \
  --target-port 8000 \
  --ingress external \
  --env-vars \
      AZURE_OPENAI_ENDPOINT=https://<tu-recurso>.openai.azure.com \
      AZURE_OPENAI_DEPLOYMENT=<tu-deployment> \
      AUTH_MODE=api_key \
  --secrets azure-openai-key=<tu-api-key> \
  --env-vars AZURE_OPENAI_API_KEY=secretref:azure-openai-key
```

Obtén la URL pública:

```bash
az containerapp show -n $APP_NAME -g $RG --query properties.configuration.ingress.fqdn -o tsv
```

Y prueba `/chat` desde tu laptop igual que en local, apuntando a esa URL.

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
