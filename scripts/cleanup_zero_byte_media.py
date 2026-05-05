from __future__ import annotations

import argparse
import json
from typing import Any

from baudoku_api.repositories.project_helpers import PROJECT_FILES_BUCKET
from baudoku_api.supabase_client import create_supabase_service_client


def _storage_size(info: dict[str, Any]) -> int | None:
    metadata = info.get("metadata")
    containers = [info, metadata] if isinstance(metadata, dict) else [info]
    for container in containers:
        for key in ("size", "contentLength", "content_length", "content-length"):
            value = container.get(key)
            if isinstance(value, int):
                return value
            if isinstance(value, str) and value.strip().isdigit():
                return int(value.strip())
    return None


def _response_data(response: Any) -> list[dict[str, Any]]:
    data = getattr(response, "data", None)
    return data if isinstance(data, list) else []


def _ids(rows: list[dict[str, Any]]) -> list[str]:
    return [str(row["id"]) for row in rows if row.get("id")]


def _media_rows(client: Any) -> list[dict[str, Any]]:
    return _response_data(client.table("media_assets").select("*").execute())


def _zero_byte_media(client: Any) -> list[dict[str, Any]]:
    bucket = client.storage.from_(PROJECT_FILES_BUCKET)
    corrupt: list[dict[str, Any]] = []
    for media in _media_rows(client):
        if media.get("deleted_at") is not None:
            continue
        storage_path = str(media.get("storage_path") or "")
        if not storage_path:
            continue
        try:
            size = _storage_size(bucket.info(storage_path))
        except Exception:
            size = None
        if size == 0:
            corrupt.append({**media, "storage_size": size})
    return corrupt


def _dependent_counts(client: Any, media_ids: list[str]) -> dict[str, int]:
    if not media_ids:
        return {}
    tables = {
        "voice_notes": "media_asset_id",
        "defect_media_links": "media_asset_id",
        "plan_files_source": "media_asset_id",
        "plan_files_preview": "preview_media_asset_id",
        "ai_jobs": "media_asset_id",
        "report_versions": "media_asset_id",
    }
    counts: dict[str, int] = {}
    for table, column in tables.items():
        table_name = table.replace("_source", "").replace("_preview", "")
        rows = _response_data(
            client.table(table_name).select("id").in_(column, media_ids).execute()
        )
        counts[table] = len(rows)
    return counts


def _delete_corrupt_media(client: Any, corrupt_media: list[dict[str, Any]]) -> dict[str, Any]:
    media_ids = _ids(corrupt_media)
    storage_paths = [str(media["storage_path"]) for media in corrupt_media]
    if not media_ids:
        return {"deleted_media": 0, "removed_storage_objects": 0}

    client.table("ai_jobs").delete().in_("media_asset_id", media_ids).execute()
    client.table("report_versions").delete().in_("media_asset_id", media_ids).execute()
    client.table("media_assets").delete().in_("id", media_ids).execute()
    removed = client.storage.from_(PROJECT_FILES_BUCKET).remove(storage_paths)
    return {
        "deleted_media": len(media_ids),
        "removed_storage_objects": len(removed) if isinstance(removed, list) else 0,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="List or delete media_assets whose Supabase Storage object is 0 bytes."
    )
    parser.add_argument("--apply", action="store_true", help="Delete corrupt rows and storage objects.")
    args = parser.parse_args()

    client = create_supabase_service_client()
    corrupt_media = _zero_byte_media(client)
    summary = {
        "mode": "apply" if args.apply else "dry-run",
        "corrupt_media_count": len(corrupt_media),
        "corrupt_media": [
            {
                "id": media["id"],
                "project_id": media["project_id"],
                "media_type": media["media_type"],
                "storage_path": media["storage_path"],
                "file_size": media.get("file_size"),
                "storage_size": media.get("storage_size"),
            }
            for media in corrupt_media
        ],
        "dependent_counts": _dependent_counts(client, _ids(corrupt_media)),
    }
    if args.apply:
        summary["cleanup"] = _delete_corrupt_media(client, corrupt_media)
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
