from __future__ import annotations

import logging
from typing import Any, Optional

from baudoku_api.repositories.project_helpers import (
    PROJECT_FILES_BUCKET,
    MediaUploadIntegrityError,
    ProjectRepositoryError,
)

logger = logging.getLogger(__name__)


class ProjectMediaIntegrityMixin:
    def _verify_completed_storage_upload(self, project_id: str, payload: Any) -> int:
        storage_path = str(payload.storage_path)
        storage_info = self._storage_object_info(storage_path)
        storage_size = self._storage_object_size(storage_info)
        if storage_size is None:
            storage_size = len(self._download_uploaded_media_bytes(storage_path))

        client_size = payload.file_size
        log_context = {
            "project_id": project_id,
            "media_id": str(payload.media_id),
            "storage_path": storage_path,
            "mime_type": str(payload.mime_type),
            "media_type": str(payload.media_type),
            "client_size": client_size,
            "storage_size": storage_size,
        }
        if storage_size <= 0:
            logger.warning("Rejected empty media upload.", extra=log_context)
            raise MediaUploadIntegrityError(
                "Upload ist leer oder unvollstaendig.",
                "UPLOAD_EMPTY_OR_INCOMPLETE",
            )
        if client_size is not None and int(client_size) != storage_size:
            logger.warning("Rejected media upload size mismatch.", extra=log_context)
            raise MediaUploadIntegrityError(
                "Upload-Groesse stimmt nicht mit der Datei ueberein.",
                "UPLOAD_SIZE_MISMATCH",
            )
        return storage_size

    def _storage_object_info(self, storage_path: str) -> dict[str, Any]:
        try:
            info = self._client.storage.from_(PROJECT_FILES_BUCKET).info(storage_path)
        except Exception as exc:  # pragma: no cover - storage exception surface
            raise MediaUploadIntegrityError(
                "Upload wurde nicht in Storage gefunden.",
                "UPLOAD_MISSING",
            ) from exc
        return info if isinstance(info, dict) else {}

    def _storage_object_size(self, storage_info: dict[str, Any]) -> Optional[int]:
        metadata = storage_info.get("metadata")
        containers = [storage_info]
        if isinstance(metadata, dict):
            containers.append(metadata)
        for container in containers:
            for key in ("size", "contentLength", "content_length", "content-length"):
                size = self._int_storage_size(container.get(key))
                if size is not None:
                    return size
        return None

    def _int_storage_size(self, value: Any) -> Optional[int]:
        if isinstance(value, bool) or value is None:
            return None
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
        if isinstance(value, str):
            stripped = value.strip()
            return int(stripped) if stripped.isdigit() else None
        return None

    def _download_uploaded_media_bytes(self, storage_path: str) -> bytes:
        try:
            return self._client.storage.from_(PROJECT_FILES_BUCKET).download(storage_path)
        except Exception as exc:  # pragma: no cover - storage exception surface
            raise MediaUploadIntegrityError(
                "Upload-Groesse konnte nicht geprueft werden.",
                "UPLOAD_SIZE_UNKNOWN",
            ) from exc

    def _download_media_bytes(self, media: dict[str, Any]) -> bytes:
        try:
            content = self._client.storage.from_(PROJECT_FILES_BUCKET).download(
                str(media["storage_path"])
            )
        except Exception as exc:  # pragma: no cover - storage exception surface
            raise ProjectRepositoryError("Datei konnte nicht fuer KI geladen werden.") from exc
        if len(content) <= 0:
            raise ProjectRepositoryError("Datei fuer KI ist leer oder Upload unvollstaendig.")
        return content

    def _download_report_image(self, storage_path: str) -> bytes:
        try:
            return self._client.storage.from_(PROJECT_FILES_BUCKET).download(storage_path)
        except Exception as exc:  # pragma: no cover - storage exception surface
            raise ProjectRepositoryError("Bild konnte nicht fuer Bericht geladen werden.") from exc
