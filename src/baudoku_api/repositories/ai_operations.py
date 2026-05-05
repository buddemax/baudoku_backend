from __future__ import annotations

from typing import Any

from baudoku_api.ai import AiProviderProtocol
from baudoku_api.domain import AuthenticatedUser

from baudoku_api.repositories.project_helpers import (
    ProjectNotFoundError,
    ProjectRepositoryError,
    _now_iso,
)


class ProjectAiMixin:
    def start_ai_transcription(
        self, voice_note_id: str, user: AuthenticatedUser, ai_provider: AiProviderProtocol
    ) -> dict[str, Any]:
        job, created = self.queue_ai_transcription(voice_note_id, user, ai_provider)
        if not created:
            return job
        return self.process_ai_transcription_job(str(job["id"]), voice_note_id, user, ai_provider)

    def queue_ai_transcription(
        self, voice_note_id: str, user: AuthenticatedUser, ai_provider: AiProviderProtocol
    ) -> tuple[dict[str, Any], bool]:
        voice_note = self._get_voice_note_for_user(voice_note_id, user.id)
        project = self.get_project(str(voice_note["project_id"]), user.id)
        media = self._get_media_asset(str(voice_note["media_asset_id"]))
        if media.get("media_type") != "audio":
            raise ProjectRepositoryError("KI-Transkription benoetigt eine Audio-Datei.")

        existing_job = self._active_ai_job(
            str(project["id"]), str(media["id"]), "transcribe_audio", voice_note_id
        )
        if existing_job is not None:
            return existing_job, False

        job = self._create_ai_job(
            str(project["id"]),
            str(media["id"]),
            "transcribe_audio",
            ai_provider.provider_name,
            self._ai_input_ref("voice_note", voice_note_id, str(media["storage_path"])),
        )
        return job, True

    def process_ai_transcription_job(
        self,
        job_id: str,
        voice_note_id: str,
        user: AuthenticatedUser,
        ai_provider: AiProviderProtocol,
    ) -> dict[str, Any]:
        voice_note = self._get_voice_note_for_user(voice_note_id, user.id)
        project = self.get_project(str(voice_note["project_id"]), user.id)
        media = self._get_media_asset(str(voice_note["media_asset_id"]))
        if media.get("media_type") != "audio":
            raise ProjectRepositoryError("KI-Transkription benoetigt eine Audio-Datei.")

        try:
            claimed_job = self._claim_ai_job_processing(job_id)
            if claimed_job is None:
                current_job = self._select_one("ai_jobs", "id", job_id)
                if current_job is None:
                    raise ProjectNotFoundError("KI-Job nicht gefunden.")
                return current_job
            audio_bytes = self._download_media_bytes(media)
            result_text = ai_provider.transcribe_audio(
                audio_bytes,
                str(media["mime_type"]),
                str(media["storage_path"]).rsplit("/", maxsplit=1)[-1],
                project,
                str(voice_note["target_type"]),
            )
            updated_job = self._complete_ai_job(job_id, result_text)
            self._execute(
                self._client.table("voice_notes")
                .update(
                    {
                        "transcript": result_text,
                        "transcript_status": "suggested",
                        "error_message": None,
                        "updated_at": _now_iso(),
                    }
                )
                .eq("id", voice_note_id)
            )
            self._record_activity(
                str(project["id"]), user.id, "ai.transcription_done", "ai_job", job_id
            )
            return updated_job
        except Exception as exc:
            error_message = str(exc) or "KI-Transkription fehlgeschlagen."
            failed_job = self._fail_ai_job(job_id, error_message)
            self._execute(
                self._client.table("voice_notes")
                .update(
                    {
                        "transcript_status": "error",
                        "error_message": error_message,
                        "updated_at": _now_iso(),
                    }
                )
                .eq("id", voice_note_id)
            )
            return failed_job

    def start_ai_image_description(
        self, media_asset_id: str, user: AuthenticatedUser, ai_provider: AiProviderProtocol
    ) -> dict[str, Any]:
        media = self._get_media_asset(media_asset_id)
        project = self.get_project(str(media["project_id"]), user.id)
        if media.get("media_type") != "photo":
            raise ProjectRepositoryError("KI-Bildbeschreibung benoetigt ein Foto.")

        existing_job = self._active_ai_job(
            str(project["id"]), media_asset_id, "describe_image", media_asset_id
        )
        if existing_job is not None:
            return existing_job

        job = self._create_ai_job(
            str(project["id"]),
            media_asset_id,
            "describe_image",
            ai_provider.provider_name,
            self._ai_input_ref("media_asset", media_asset_id, str(media["storage_path"])),
        )
        try:
            self._mark_ai_job_processing(str(job["id"]))
            image_bytes = self._download_media_bytes(media)
            result_text = ai_provider.describe_image(image_bytes, str(media["mime_type"]), project)
            updated_job = self._complete_ai_job(str(job["id"]), result_text)
            self._execute(
                self._client.table("media_assets")
                .update(
                    {
                        "caption": result_text,
                        "caption_status": "suggested",
                        "updated_at": _now_iso(),
                    }
                )
                .eq("id", media_asset_id)
            )
            self._record_activity(
                str(project["id"]), user.id, "ai.image_description_done", "ai_job", str(job["id"])
            )
            return updated_job
        except Exception as exc:
            error_message = str(exc) or "KI-Bildbeschreibung fehlgeschlagen."
            failed_job = self._fail_ai_job(str(job["id"]), error_message)
            self._execute(
                self._client.table("media_assets")
                .update({"caption_status": "error", "updated_at": _now_iso()})
                .eq("id", media_asset_id)
            )
            return failed_job

    def get_ai_job(self, job_id: str, user_id: str) -> dict[str, Any]:
        job = self._select_one("ai_jobs", "id", job_id)
        if job is None:
            raise ProjectNotFoundError("KI-Job nicht gefunden.")
        self.get_project(str(job["project_id"]), user_id)
        return job
