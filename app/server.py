from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from urllib.parse import parse_qs
from pathlib import Path
from mimetypes import guess_type
from mistral_repsol_faq_qa_loop_simpl import main  # Cambiar si no es main

class SimpleHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        content_length = int(self.headers['Content-Length'])
        body = self.rfile.read(content_length).decode('utf-8')
        data = parse_qs(body)
        pregunta = data.get("pregunta", [""])[0]

        respuesta = main(pregunta) # ⚠️ Cambiar si la función es diferente

        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps({"respuesta": respuesta}).encode('utf-8'))

    def do_GET(self):
        if self.path == "/":
            self.serve_file("web/index.html", "text/html")
        else:
            # Servir archivos estáticos
            file_path = Path("web" + self.path).resolve()
            if file_path.is_file():
                mime_type, _ = guess_type(str(file_path))
                self.serve_file(file_path, mime_type or "application/octet-stream")
            else:
                self.send_error(404, "Archivo no encontrado")

    def serve_file(self, path, mime_type):
        try:
            with open(path, "rb") as f:
                self.send_response(200)
                self.send_header("Content-type", mime_type)
                self.end_headers()
                self.wfile.write(f.read())
        except Exception as e:
            self.send_error(500, f"Error interno del servidor: {e}")

if __name__ == "__main__":
    print("Servidor corriendo en http://localhost:8000")
    HTTPServer(("0.0.0.0", 8000), SimpleHandler).serve_forever()
