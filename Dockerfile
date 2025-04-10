# Imagen base ligera de Python 3.11
FROM python:3.11-slim

# Directorio de trabajo dentro del contenedor
WORKDIR /app

COPY app/ .

# Instalar dependencias necesarias
RUN pip install --no-cache-dir \
    flask \
    elasticsearch \
    requests \
    sentence-transformers \
    numpy \
    redis

# Exponer el puerto que usará el servidor web
EXPOSE 5000

# Comando por defecto al iniciar el contenedor
CMD ["python", "server.py"]
