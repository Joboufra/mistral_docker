# Etapa 1: build
FROM python:3.11-slim-bullseye AS builder

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

RUN pip install --upgrade pip && \
    pip install --user --no-cache-dir -r requirements.txt

# Etapa 2: final image (runtime)
FROM python:3.11-slim-bullseye

WORKDIR /app

# Copiamos solo lo necesario desde la etapa de build
COPY --from=builder /root/.local /root/.local
COPY app/ .

# Variables de entorno para que Python no genere .pyc y loguee en consola
ENV PATH=/root/.local/bin:$PATH \
    PYTHONUNBUFFERED=1

EXPOSE 5000

CMD ["python", "server.py"]
