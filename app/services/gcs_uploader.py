"""verificar_gcs.py — versión simple"""
from dotenv import load_dotenv
load_dotenv()

import os
from app.services.gcs_uploader import get_gcs_uploader

uploader = get_gcs_uploader()

url = uploader.subir_imagen(
    file_bytes=b"prueba electro " + os.urandom(8),
    path="electro/test/verificar.txt",
    content_type="text/plain",
)

print(f"✅ Subido OK\nURL: {url}")