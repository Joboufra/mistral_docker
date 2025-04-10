#!/usr/bin/env bash

if ! command -v elasticdump &>/dev/null; then
  echo "elasticdump no está instalado. Instalando..."
  
  if [ "$EUID" -ne 0 ]; then
    sudo npm install -g elasticdump
  else
    npm install -g elasticdump
  fi
else
  echo "elasticdump ya está instalado."
fi

echo "Exportando mappings..."
NODE_TLS_REJECT_UNAUTHORIZED=0 elasticdump \
  --input=faq-repsol-embeddings-template.json \
  --output=https://elastic:changeme@localhost:9200/faq-repsol-embeddings \
  --type=mapping

echo "Exportando datos..."
NODE_TLS_REJECT_UNAUTHORIZED=0 elasticdump \
  --input=faq-repsol-embeddings-docs.json \
  --output=https://elastic:changeme@localhost:9200/faq-repsol-embeddings \
  --type=data

echo "Proceso finalizado."
