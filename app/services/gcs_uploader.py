"""
Verificación rápida de GCS antes de empadronar.
Borra este archivo después de usarlo.
"""
import os
from dotenv import load_dotenv

load_dotenv()

from app.services.gcs_uploader import GCSUploader

bucket = os.getenv("GCS_BUCKET_NAME")
sa_json = os.getenv("GCS_SERVICE_ACCOUNT_JSON")
project = os.getenv("GCS_PROJECT_ID")

print(f"Bucket: {bucket}")
print(f"Project: {project}")
print(f"SA JSON length: {len(sa_json) if sa_json else 'VACIO'}")

if not bucket or not sa_json:
    print("\n❌ Faltan variables. Verifica tu .env")
    raise SystemExit(1)

uploader = GCSUploader(
    bucket_name=bucket,
    service_account_json=sa_json,
    project_id=project,
)

url = uploader.subir_imagen(
    file_bytes=b"prueba electro " + os.urandom(8),
    path="electro/test/verificar.txt",
    content_type="text/plain",
)

print(f"\n✅ Subido OK")
print(f"URL: {url}")
print(f"\nAbre esa URL en el navegador. Debes ver 'prueba electro' + caracteres binarios.")