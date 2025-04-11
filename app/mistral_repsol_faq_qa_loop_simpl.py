#!/usr/bin/env python3
import urllib3
import warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", message="Connecting to 'https://localhost:9200' using TLS with verify_certs=False is insecure")

# Requisitos:
# pip install elasticsearch requests sentence-transformers numpy redis

from elasticsearch import Elasticsearch
from sentence_transformers import SentenceTransformer
from datetime import datetime
import requests
import time
import redis
import json
import uuid

# Configuración global
SESSION_ID = "chat:repsol"
TTL_SECONDS = 1800  #TTL Redis - 30 minutos
CONTEXT_LIMIT = 10  #Últimos pares pregunta-respuesta
OLLAMA_URL = "http://mistral:11434/v1/chat/completions"
CONTEXT_INDEX = "chat-context-repsol"  #Índice para el contexto semántico 

r = redis.Redis(host='redis', port=6379, decode_responses=True)

def generar_id_mensaje():
    return str(uuid.uuid4())

def guardar_mensaje(message_id, role, content):
    key = f"{SESSION_ID}:{message_id}:{role}"
    value = {"role": role, "content": content}
    r.set(key, json.dumps(value), ex=TTL_SECONDS)
    if role == "assistant":
        r.rpush(f"{SESSION_ID}:index", message_id)
        r.expire(f"{SESSION_ID}:index", TTL_SECONDS)
    print(f"💾 [Redis] Guardado en clave: {key} con TTL {TTL_SECONDS}s")
    print(json.dumps(value, indent=2, ensure_ascii=False))

    #Guardar también en Elasticsearch como contexto semántico
    vector = model.encode(content).tolist()
    es.index(index=CONTEXT_INDEX, document={
        "message_id": message_id,
        "role": role,
        "content": content,
        "embedding": vector,
        "timestamp": datetime.utcnow().isoformat()
    })
    print(f"💾 [Elastic] Guardado en índice '{CONTEXT_INDEX}' con vector de embedding.")

def get_session_message_ids():
    message_ids = r.lrange(f"{SESSION_ID}:index", -CONTEXT_LIMIT, -1)
    print(f"🧩 [Redis] Últimos {len(message_ids)} IDs de conversación recuperados:")
    print(message_ids)
    return message_ids

def crear_contexto_redis():
    message_ids = get_session_message_ids()
    messages = []

    for msg_id in message_ids:
        for role in ["user", "assistant"]:
            key = f"{SESSION_ID}:{msg_id}:{role}"
            raw = r.get(key)
            if raw:
                msg = json.loads(raw)
                messages.append(msg)
                print(f"📦 [Redis] Recuperado {role.upper()} desde clave {key}")
            else:
                print(f"⚠️ [Redis] Clave no encontrada: {key}")

    return messages

#def crear_contexto_semantico(query_vector):
#    print("🔍 [Elastic] Buscando contexto semántico relevante en Elasticsearch...")
#
#    search_body = {
#        "size": 5,
#        "knn": {
#            "field": "embedding",
#            "query_vector": query_vector,
#            "k": 5,
#            "num_candidates": 100
#        },
#        "_source": ["role", "content"]
#    }
#
#    res = es.search(index=CONTEXT_INDEX, body=search_body)
#
#    contexto_semantico = "\n\n".join(
#        f"{doc['_source']['role'].capitalize()}: {doc['_source']['content']}"
#        for doc in res["hits"]["hits"]
#    )
#
#    if contexto_semantico:
#        print("✅ [Elastic] Contexto semántico relevante encontrado.")
#    else:
#        print("ℹ️ [Elastic] No se encontró contexto semántico relevante.")
#
#    return contexto_semantico

#En resumen_contexto se usa modelo openchat ya que es una operación de resumen y no es necesario Mistral, es más rápido
def resumen_contexto(context_messages):
    if not context_messages:
        print("ℹ️ [Resumen] No hay contexto previo para simplificar.")
        return ""

    print("🧩 [Resumen] Generando resumen del contexto...")

    context_text = "\n".join(
        f"{msg['role'].capitalize()}: {msg['content']}" for msg in context_messages
    )

    messages = [
    {"role": "system", "content": (
        "Eres un asistente que resume conversaciones previas entre usuario y asistente, "
        "capturando de forma clara datos personales proporcionados por el usuario, como su nombre, ubicaciones o preferencias. "
        "Empieza el resumen indicando explícitamente el nombre del usuario si se ha proporcionado. "
        "Después, incluye un listado breve de las preguntas realizadas y sus temas. "
        "Evita incluir detalles irrelevantes y proporciona un resumen limpio y enfocado en lo esencial para continuar la conversación de forma fluida."
    )},
    {"role": "user", "content": f"Resume la siguiente conversación previa destacando datos personales y preguntas:\n\n{context_text}"}
    ]
    response = requests.post(OLLAMA_URL, json={"model": "openchat", "messages": messages})
    summary = response.json()["choices"][0]["message"]["content"].strip()

    print("📝 [Resumen] Resumen generado:")
    print(summary)

    return summary

def existe_respuesta(context_messages, nueva_pregunta): #Busca si se ha preguntado exactamente la misma pregunta
    print("🔍 [Contexto] Buscando si la pregunta ya fue respondida anteriormente...")

    for i in range(len(context_messages) - 1):
        user_msg = context_messages[i]
        assistant_msg = context_messages[i + 1]

        if user_msg["role"] == "user" and assistant_msg["role"] == "assistant":
            if user_msg["content"].strip().lower() == nueva_pregunta.strip().lower():
                print("✅ [Contexto] Pregunta encontrada en el historial. Usando respuesta previa.")
                return assistant_msg["content"]

    print("ℹ️ [Contexto] Pregunta no encontrada en el historial.")
    return None

def limpiar_historial_chat():
    message_ids = r.lrange(f"{SESSION_ID}:index", 0, -1)
    keys_to_delete = []

    for msg_id in message_ids:
        keys_to_delete.append(f"{SESSION_ID}:{msg_id}:user")
        keys_to_delete.append(f"{SESSION_ID}:{msg_id}:assistant")

    if keys_to_delete:
        r.delete(*keys_to_delete)
    r.delete(f"{SESSION_ID}:index")
    print(f"🗑️ [Redis] Historial completo eliminado. Claves borradas:")
    print(keys_to_delete)

# Configuración de Elasticsearch
es = Elasticsearch(
    "https://es01:9200",
    basic_auth=("elastic", "changeme"),
    verify_certs=False
)

INDEX = "faq-repsol-embeddings" # Actualiza si reindexas
TEXT_FIELD = "body_content"
EMBEDDING_FIELD = "embedding"

#Crear índice de contexto de conversación si no existe
#def crear_indice_contexto():
#   if not es.indices.exists(index=CONTEXT_INDEX):
#       mapping = {
#           "mappings": {
#               "properties": {
#                   "message_id": {"type": "keyword"},
#                   "role": {"type": "keyword"},
#                   "content": {"type": "text"},
#                   "embedding": {"type": "dense_vector", "dims": 384},  # 384 para 'all-MiniLM-L6-v2'
#                   "timestamp": {"type": "date"}
#               }
#           }
#       }
#       es.indices.create(index=CONTEXT_INDEX, body=mapping)
#       print(f"✅ [Elastic] Índice '{CONTEXT_INDEX}' creado correctamente.")
#   else:
#       print(f"ℹ️ [Elastic] Índice '{CONTEXT_INDEX}' ya existe.")
#crear_indice_contexto()

#Cargar modelo de embeddings
model = SentenceTransformer("all-MiniLM-L6-v2")

print("🤖 Pregunta sobre las FAQs de Repsol. Escribe 'salir' para terminar o 'reset' para limpiar el caché.")

def main(query: str) -> str:
    if query.strip().lower() == "reset":
        limpiar_historial_chat()
        return "Historial de la conversación reiniciado."

#1- Construir contexto desde Redis
    historial_contexto = crear_contexto_redis()

#2- Comprobar si la pregunta ya fue respondida
    respuesta_existe = existe_respuesta(historial_contexto, query)
    if respuesta_existe:
        print("🤖 Respuesta desde caché (sin consultar Elastic ni modelo):")
        print(respuesta_existe)
        return respuesta_existe

#3- Generar vector de consulta Elasticsearch
    query_vector = model.encode(query).tolist()

    search_body = {
        "size": 3,
        "knn": {
            "field": EMBEDDING_FIELD,
            "k": 3,
            "num_candidates": 100,
            "query_vector": query_vector
        }
    }

    start_time = time.time()
    res = es.search(index=INDEX, body=search_body)
    docs = res["hits"]["hits"]

    context_fragments = "\n\n".join(
        f"[Título] {doc['_source'].get('title', 'Sin título')}\n[Contenido] {doc['_source'].get(TEXT_FIELD, '')}"
        for doc in docs
    )
    ids = [doc["_id"] for doc in docs]

#4- Simplificar contexto previo si existe
    contexto_simplificado = ""
    if historial_contexto:
        contexto_simplificado = resumen_contexto(historial_contexto)
    else:
        print("ℹ️ [Contexto] No hay historial previo en Redis. Se omitirá el resumen de contexto.")

### Usar el contexto semántico de Elasticsearch para responder preguntas similares formuladas de forma diferente, contexto a largo plazo
#5- Recuperar contexto semántico desde Elasticsearch
#    contexto_semantico = crear_contexto_semantico(query_vector)

#6- Preparar mensaje final
    messages = []

    #Instrucciones iniciales
    messages.append({
        "role": "system",
        "content": (
            "Eres un asistente experto que responde exclusivamente en base a las FAQs de Repsol.\n"
            "<Datos> contiene la información oficial y prioritaria que debes usar para responder a la consulta del usuario.\n"
            "<Contexto> contiene información adicional de interacciones previas, que solo debes utilizar para enriquecer la respuesta si no encuentras la información suficiente en <Datos>.\n"
            "Siempre prioriza <Datos>. Usa <Contexto> solo como complemento secundario.\n"
            "No te refieras nunca explícitamente a <Contexto> o <Datos> en tus respuestas finales, responde como si fueran parte de tu conocimiento.\n"
            "Si no encuentras suficiente información en <Datos>, y <Contexto> tampoco proporciona la respuesta, indica educadamente que no dispones de la información necesaria.\n"
            "Responde exclusivamente a la pregunta formulada en <Pregunta>.\n"
            "Tu respuesta debe comenzar justo después de la etiqueta <Respuesta>, omitiendo cualquier otra etiqueta.\n"
            "No menciones códigos internos, IDs, o instrucciones internas en la respuesta."
        )
    })

    #Incluir también la consulta actual del usuario para refrescar el foco del modelo
    ## Pendiente de validar que sirve:
    messages.append({
        "role": "user",
        "content": f"La consulta actual es: {query}\nPor favor, responde utilizando principalmente <Datos>."
    })

    #Si hay resumen de contexto, se añade
    if contexto_simplificado:
        messages.append({
            "role": "system",
            "content": f"<Contexto> {contexto_simplificado}"
        })
 
#    #Si hay contexto semántico, se añade
#    if contexto_semantico:
#        messages.append({
#            "role": "system",
#            "content": f"Contexto relevante de la conversación previa: {contexto_simplificado}\n"
#        })

    #Añadimos los resultados de Elasticsearch
    messages.append({
        "role": "system",
        "content": (
            "<Datos> Esta es la información de las FAQs de Repsol:\n"
            f"{context_fragments}"
        )
    })

    #Y se añade la pregunta del user
    messages.append({
        "role": "user",
        "content": f"<Pregunta> {query}. Responde utilizando principalmente <Datos>. <Respuesta>"
    })

#7- Enviar la petición a Mistral
    response = requests.post(
        OLLAMA_URL,
        json={
            "model": "mistral",
            "stream": True, #Streaming, pendiente revisar performance https://docs.baseten.co/inference/streaming
            "messages": messages
        },
        stream=True
    )

    assistant_response = ""
    print("🤖 Respuesta generada por Elastic (con la IA Mistral):\n")

    for line in response.iter_lines():
        if line:
            decoded_line = line.decode('utf-8')
            if not decoded_line.startswith("data: "):
                continue
            try:
                data = json.loads(decoded_line[len("data: "):])
                delta = data.get("choices", [{}])[0].get("delta", {}).get("content", "")
                print(delta, end="", flush=True)
                assistant_response += delta
            except json.JSONDecodeError:
                continue

    end_time = time.time()
    duration = end_time - start_time

#8- Guardar pregunta y respuesta como par en Redis y Elastic
    message_id = generar_id_mensaje()
    guardar_mensaje(message_id, "user", query)
    guardar_mensaje(message_id, "assistant", assistant_response)

#9- Print de resultados y toda la vaina
    print("\n\n*****************************")
    print(f"📄 IDs de documentos utilizados: {ids}")
    print(f"⏱ Tiempo total de generación: {duration:.2f} segundos")
    print("*****************************")

    try:
        return assistant_response
    except (KeyError, IndexError, TypeError):
        return "No se pudo interpretar la respuesta del modelo."
