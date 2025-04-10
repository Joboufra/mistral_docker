#!/usr/bin/env python3
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
import warnings
warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", message="Connecting to 'https://localhost:9200' using TLS with verify_certs=False is insecure")

# Requisitos:
# pip install elasticsearch requests sentence-transformers numpy redis

from elasticsearch import Elasticsearch
from sentence_transformers import SentenceTransformer
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

def resumen_contexto(context_messages):
    if not context_messages:
        print("ℹ️ [Resumen] No hay contexto previo para simplificar.")
        return ""

    print("🧩 [Resumen] Generando resumen del contexto...")

    context_text = "\n".join(
        f"{msg['role'].capitalize()}: {msg['content']}" for msg in context_messages
    )

    messages = [
        {"role": "system", "content": "Eres un asistente que resume conversaciones previas de usuario y asistente en frases cortas que capturen el contexto de lo que se ha hablado anteriorme. Indicarás la información más relevante de forma resumida"},
        {"role": "user", "content": f"Resume la siguiente conversación previa:\n\n{context_text}"}
    ]

    response = requests.post(OLLAMA_URL, json={"model": "openchat", "messages": messages})
    summary = response.json()["choices"][0]["message"]["content"].strip()

    print("📝 [Resumen] Resumen generado:")
    print(summary)

    return summary

def existe_respuesta(context_messages, new_question):
    print("🔍 [Contexto] Buscando si la pregunta ya fue respondida anteriormente...")

    for i in range(len(context_messages) - 1):
        user_msg = context_messages[i]
        assistant_msg = context_messages[i + 1]

        if user_msg["role"] == "user" and assistant_msg["role"] == "assistant":
            if user_msg["content"].strip().lower() == new_question.strip().lower():
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

# Cargar modelo de embeddings
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
        print("🤖 Respuesta desde el contexto previo (sin consultar Elastic ni modelo):")
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
        f"Título: {doc['_source'].get('title', 'Sin título')}\nContenido: {doc['_source'].get(TEXT_FIELD, '')}"
        for doc in docs
    )
    ids = [doc["_id"] for doc in docs]

#4- Simplificar contexto previo si existe
    contexto_simplificado = ""
    if historial_contexto:
        contexto_simplificado = resumen_contexto(historial_contexto)
    else:
        print("ℹ️ [Contexto] No hay historial previo en Redis. Se omitirá el resumen de contexto.")

#5- Preparar mensaje final
    messages = []

    #Instrucciones iniciales
    messages.append({
        "role": "system",
        "content": (
            "Eres un asistente inteligente que responde exclusivamente en base a las FAQs de Repsol. "
            "No debes generalizar ni hablar de otras empresas."
            "Proporciona respuestas claras y concisas basadas únicamente en la información disponible."
        )
    })

    #Si hay contexto, se añade como recordatorio de la conversación previa
    if contexto_simplificado:
        messages.append({
            "role": "system",
            "content": f"Resumen del contexto de la conversación previa: {contexto_simplificado}"
        })

    #Añadimos los resultado de Elasticsearch
    messages.append({
        "role": "system",
        "content": (
            "A continuación tienes un conjunto de fragmentos extraídos de las FAQs de Repsol para que los tengas en cuenta al responder:\n\n"
            f"{context_fragments}"
        )
    })

    #Y se añade la pregunta del user
    messages.append({
        "role": "user",
        "content": query
    })

#6- Enviar la petición a Mistral con streaming
    response = requests.post(
        OLLAMA_URL,
        json={
            "model": "openchat",
            "stream": True,
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

#7- Guardar pregunta y respuesta como par en Redis
    message_id = generar_id_mensaje()
    guardar_mensaje(message_id, "user", query)
    guardar_mensaje(message_id, "assistant", assistant_response)

#8- Print de resultados y toda la vaina
    print("\n\n*****************************")
    print(f"📄 IDs de documentos utilizados: {ids}")
    print(f"⏱ Tiempo total de generación: {duration:.2f} segundos")
    print("*****************************")

    try:
        return assistant_response
    except (KeyError, IndexError, TypeError):
        return "No se pudo interpretar la respuesta del modelo."
