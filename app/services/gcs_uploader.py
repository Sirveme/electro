"""
Subida de imágenes a Google Cloud Storage.

- El bucket está configurado con uniform bucket-level access. No usamos make_public().
- La URL se construye directamente: https://storage.googleapis.com/{bucket}/{path}
- Credenciales: variable de entorno GCS_SERVICE_ACCOUNT_JSON con el JSON de service account
  (no la ruta, el contenido como string).
"""
import json
import logging
import os
from io import BytesIO
from typing import Optional

logger = logging.getLogger(__name__)


class GCSUploaderError(Exception):
    pass


class GCSUploader:
    def __init__(
        self,
        bucket_name: str,
        service_account_json: str,
        project_id: Optional[str] = None,
    ):
        if not bucket_name:
            raise GCSUploaderError("GCS_BUCKET_NAME no configurado")
        if not service_account_json:
            raise GCSUploaderError("GCS_SERVICE_ACCOUNT_JSON no configurado")

        try:
            info = json.loads(service_account_json)
        except json.JSONDecodeError as exc:
            raise GCSUploaderError(f"GCS_SERVICE_ACCOUNT_JSON no es JSON válido: {exc}") from exc

        # Import diferido para no romper el arranque si el paquete no está instalado en dev
        from google.cloud import storage  # type: ignore
        from google.oauth2 import service_account  # type: ignore

        creds = service_account.Credentials.from_service_account_info(info)
        self._client = storage.Client(
            credentials=creds,
            project=project_id or info.get("project_id"),
        )
        self._bucket_name = bucket_name
        self._bucket = self._client.bucket(bucket_name)

    def subir_imagen(
        self,
        file_bytes: bytes,
        path: str,
        content_type: str = "image/jpeg",
    ) -> str:
        """Sube bytes al path indicado y retorna la URL pública directa."""
        try:
            blob = self._bucket.blob(path)
            blob.upload_from_file(BytesIO(file_bytes), content_type=content_type, rewind=True)
        except Exception as exc:
            logger.exception("Error subiendo a GCS path=%s", path)
            raise GCSUploaderError(f"Error subiendo a GCS: {exc}") from exc

        return f"https://storage.googleapis.com/{self._bucket_name}/{path}"

    def eliminar(self, path: str) -> None:
        """Elimina un objeto. No lanza si no existe."""
        try:
            blob = self._bucket.blob(path)
            blob.delete()
        except Exception:
            logger.exception("Error eliminando de GCS path=%s (continuando)", path)


_singleton: Optional[GCSUploader] = None


def get_gcs_uploader() -> GCSUploader:
    """Singleton lazy. Lee env vars en el primer uso."""
    global _singleton
    if _singleton is None:
        _singleton = GCSUploader(
            bucket_name=os.getenv("GCS_BUCKET_NAME", ""),
            service_account_json=os.getenv("GCS_SERVICE_ACCOUNT_JSON", ""),
            project_id=os.getenv("GCS_PROJECT_ID") or None,
        )
    return _singleton