
# 🧠 Mistral + Elastic Stack Demo (Extended)

Este proyecto contiene un entorno completo de contenedores Docker que integra:

- Un modelo de lenguaje local (`Mistral` via Ollama) compatible con la API de OpenAI.
- Un stack completo de observabilidad con Elasticsearch, Kibana y Enterprise Search.
- Una aplicación web personalizada que consulta Elasticsearch y genera respuestas con Mistral.
- Gestión de conversación enriquecida con Redis para mantener el estado del chat y Elasticsearch para contexto semántico extendido.

---

## Supuestos

El elasticsearch estará vacío por defecto.  
Debes cargar el template y los datos iniciales desde la carpeta `example-info` usando `elasticdump`.

---

## 📦 Servicios incluidos

| Servicio             | Descripción |
|---------------------|-------------|
| `mistral`           | Contenedor con el modelo de lenguaje `mistral` accesible vía `/v1/chat/completions`. |
| `app`               | Aplicación web en Python que permite hacer preguntas a las FAQs de Repsol. |
| `es01`              | Nodo principal de Elasticsearch con certificados y autenticación. |
| `kibana`            | Interfaz de visualización para Elasticsearch. |
| `enterprisesearch`  | API de búsqueda empresarial y gestión de contenido. |
| `setup`             | Inicializa los certificados SSL y credenciales necesarias. |
| `redis`             | Motor de caché en memoria para almacenamiento rápido de contexto de chat. |

---

## 🚀 Cómo usar

### 1. Requisitos previos

- Docker + Docker Compose instalados.
- Sistema operativo: **Linux x86_64**.
- GPU disponible (en este caso, NVIDIA con CUDA cores disponibles)
- Archivo `.env` configurado:

```env
STACK_VERSION=8.15.1
ELASTIC_PASSWORD=changeme
KIBANA_PASSWORD=changeme
CLUSTER_NAME=es-cluster
LICENSE=basic
MEM_LIMIT=4294967296
ES_PORT=9200
KIBANA_PORT=5601
ENTERPRISE_SEARCH_PORT=3002
ENCRYPTION_KEYS=supersecretkey
```

---

### 2. Clonar y levantar servicios

```bash
git clone <este-repo>
cd mistral-docker
docker compose --env-file .env up --build
```

Esto:

- Construirá la aplicación `app`.
- Levantará todos los servicios en red compartida.
- Inicializará certificados y configuraciones necesarias.

---

### 3. Acceso rápido a servicios

| Servicio               | URL |
|------------------------|-----|
| App                    | http://localhost:8000 |
| Kibana                 | http://localhost:5601 |
| Enterprise Search      | http://localhost:3002 |
| Mistral API            | http://localhost:11434/v1/chat/completions |
| Redis            | redis://localhost:6379 |
---

## 🧩 Detalles técnicos del flujo de conversación

### Redis — Contexto de conversación inmediato

- Redis almacena pares **pregunta-respuesta** como claves por sesión `chat:repsol:{uuid}:{role}`.
- Cada interacción genera dos entradas: una para la pregunta del usuario (`role: user`) y otra para la respuesta del asistente (`role: assistant`).
- Los identificadores se almacenan en una lista ordenada para mantener el historial de conversación (`chat:repsol:index`).
- TTL de 30 minutos para limpiar la conversación automáticamente.
- Redis se consulta en cada nueva pregunta para:
  - Detectar si la pregunta ya fue respondida anteriormente (respuesta inmediata sin pasar por Mistral).
  - Construir un **resumen simplificado** del contexto reciente para enriquecer la petición al modelo.

### Elasticsearch — Contexto semántico extendido

- Cada mensaje también se guarda como documento en el índice `chat-context-repsol`.
- Se genera y almacena el vector de embeddings de cada contenido.
- Elasticsearch se consulta para construir un **contexto semántico extendido**, con preguntas/respuestas similares a la actual aunque no sean exactas.
- Se prioriza Redis como contexto inmediato por rendimiento y Elasticsearch como contexto enriquecido.

### Modelo Mistral — Generación de respuestas

- El prompt enviado a Mistral incluye:
  - Instrucciones claras de comportamiento.
  - `<Contexto>` (conversaciones recientes de Redis resumidas).
  - `<Datos>` (información extraída de Elasticsearch).
  - `<Pregunta>` que formula el usuario.
- Mistral responde utilizando tanto `<Datos>` como `<Contexto>` para ofrecer respuestas naturales y consistentes.

---

### 4. Test del modelo vía curl

```bash
curl http://localhost:11434/v1/chat/completions   -H "Content-Type: application/json"   -d '{
    "model": "mistral",
    "messages": [
      {"role": "user", "content": "¿Qué es Repsol?"}
    ]
  }'
```

---

### 5. Parar y limpiar

```bash
docker compose down -v
```

---

### 📝 Notas adicionales

- Red de contenedores: `mistral-net`.
- Certificados generados automáticamente en el servicio `setup`.
- Redis mejora la latencia de conversación y reduce llamadas innecesarias a Elasticsearch o al modelo.
- **Flujo de prioridad: Redis ➔ Elasticsearch ➔ Mistral.**

---

### ⚠️ Compatibilidad

- ✅ **Linux x86_64** (recomendado).
- ❌ **Apple Silicon M1/M2/M3** requiere emulación (QEMU) o usar `ollama/ollama`.