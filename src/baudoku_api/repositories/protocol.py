from __future__ import annotations

from datetime import datetime
from typing import Any, Optional, Protocol

from baudoku_api.ai import AiProviderProtocol
from baudoku_api.domain import AuthenticatedUser
from baudoku_api.schemas import (
    DefectCreate,
    DefectMediaLinkCreate,
    DefectMediaLinkUpdate,
    DefectUpdate,
    GeneralFindingCreate,
    GeneralFindingUpdate,
    MediaAssetUpdate,
    MediaCompleteUploadRequest,
    MediaInitUploadRequest,
    PlanCreate,
    PlanExportRequest,
    PlanMarkerCreate,
    PlanMarkerUpdate,
    ProjectConclusionUpsert,
    ProjectCreate,
    ProjectUpdate,
    SyncOperation,
    VoiceNoteCreate,
    VoiceNoteUpdate,
)

class ProjectRepositoryProtocol(Protocol):
    def ensure_profile(self, auth_user: AuthenticatedUser) -> AuthenticatedUser:
        """Create/update the app profile for an authenticated Supabase user."""

    def list_projects(
        self,
        user_id: str,
        search: Optional[str] = None,
        status: Optional[str] = None,
        appraisal_type: Optional[str] = None,
        include_deleted: bool = False,
    ) -> list[dict[str, Any]]:
        """List all non-deleted projects visible through project_members."""

    def list_profiles(self, user_id: str) -> list[dict[str, Any]]:
        """List active app profiles visible to the current user."""

    def list_trades(self, user_id: str) -> list[dict[str, Any]]:
        """List active trades available for defect capture."""

    def create_project(self, payload: ProjectCreate, user: AuthenticatedUser) -> dict[str, Any]:
        """Create a project and its project_members rows."""

    def get_project(self, project_id: str, user_id: str) -> dict[str, Any]:
        """Return one visible project or raise ProjectNotFoundError."""

    def update_project(
        self, project_id: str, payload: ProjectUpdate, user: AuthenticatedUser
    ) -> dict[str, Any]:
        """Patch project master data/status for a visible project."""

    def delete_project(self, project_id: str, user: AuthenticatedUser) -> None:
        """Soft-delete a visible project."""

    def list_defects(
        self,
        project_id: str,
        user_id: str,
        kind: Optional[str] = None,
        trade_id: Optional[str] = None,
        category: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """List defects and notices for a visible project."""

    def create_defect(
        self, project_id: str, payload: DefectCreate, user: AuthenticatedUser
    ) -> dict[str, Any]:
        """Create a defect or notice for a visible project."""

    def update_defect(
        self, defect_id: str, payload: DefectUpdate, user: AuthenticatedUser
    ) -> dict[str, Any]:
        """Patch a defect or notice."""

    def reorder_defects(
        self, project_id: str, defect_ids: list[str], user: AuthenticatedUser
    ) -> list[dict[str, Any]]:
        """Persist the visible report order for defects and notices."""

    def init_media_upload(
        self, project_id: str, payload: MediaInitUploadRequest, user: AuthenticatedUser
    ) -> dict[str, Any]:
        """Create a signed upload token for a project file."""

    def complete_media_upload(
        self, project_id: str, payload: MediaCompleteUploadRequest, user: AuthenticatedUser
    ) -> dict[str, Any]:
        """Persist metadata for an uploaded project file."""

    def list_media_assets(
        self,
        project_id: str,
        user_id: str,
        media_type: Optional[str] = None,
        include_deleted: bool = False,
    ) -> list[dict[str, Any]]:
        """List project media with short-lived signed URLs."""

    def get_media_asset_signed_url(self, media_asset_id: str, user: AuthenticatedUser) -> dict[str, Any]:
        """Return a short-lived signed URL for one project media asset."""

    def create_defect_media_link(
        self, defect_id: str, payload: DefectMediaLinkCreate, user: AuthenticatedUser
    ) -> dict[str, Any]:
        """Attach an uploaded media asset to a defect."""

    def update_defect_media_link(
        self, link_id: str, payload: DefectMediaLinkUpdate, user: AuthenticatedUser
    ) -> dict[str, Any]:
        """Patch media link order/report inclusion."""

    def delete_defect_media_link(self, link_id: str, user: AuthenticatedUser) -> dict[str, Any]:
        """Soft-delete a media link."""

    def update_media_asset(
        self, media_asset_id: str, payload: MediaAssetUpdate, user: AuthenticatedUser
    ) -> dict[str, Any]:
        """Patch media metadata such as caption and caption status."""

    def delete_media_asset(self, media_asset_id: str, user: AuthenticatedUser) -> dict[str, Any]:
        """Soft-delete a project media asset."""

    def delete_defect(self, defect_id: str, user: AuthenticatedUser) -> dict[str, Any]:
        """Soft-delete a defect or notice."""

    def list_plans(self, project_id: str, user_id: str) -> list[dict[str, Any]]:
        """List plan files and markers for a visible project."""

    def create_plan(
        self, project_id: str, payload: PlanCreate, user: AuthenticatedUser
    ) -> dict[str, Any]:
        """Create a plan record from an uploaded media asset."""

    def create_plan_marker(
        self, plan_id: str, payload: PlanMarkerCreate, user: AuthenticatedUser
    ) -> dict[str, Any]:
        """Create a normalized plan marker."""

    def update_plan_marker(
        self, marker_id: str, payload: PlanMarkerUpdate, user: AuthenticatedUser
    ) -> dict[str, Any]:
        """Patch a plan marker."""

    def delete_plan_marker(self, marker_id: str, user: AuthenticatedUser) -> None:
        """Soft-delete a plan marker."""

    def export_plan(
        self, plan_id: str, payload: PlanExportRequest, user: AuthenticatedUser
    ) -> dict[str, Any]:
        """Render a marked plan export and return a short-lived download URL."""

    def list_voice_notes(self, project_id: str, user_id: str) -> list[dict[str, Any]]:
        """List voice notes for a visible project."""

    def create_voice_note(
        self, project_id: str, payload: VoiceNoteCreate, user: AuthenticatedUser
    ) -> dict[str, Any]:
        """Create a voice note for an uploaded audio media asset."""

    def update_voice_note(
        self, voice_note_id: str, payload: VoiceNoteUpdate, user: AuthenticatedUser
    ) -> dict[str, Any]:
        """Patch a voice note target or transcript fields."""

    def delete_voice_note(self, voice_note_id: str, user: AuthenticatedUser) -> dict[str, Any]:
        """Soft-delete a voice note."""

    def list_general_findings(self, project_id: str, user_id: str) -> list[dict[str, Any]]:
        """List general findings for a visible project."""

    def create_general_finding(
        self, project_id: str, payload: GeneralFindingCreate, user: AuthenticatedUser
    ) -> dict[str, Any]:
        """Create a general finding for a visible project."""

    def update_general_finding(
        self, finding_id: str, payload: GeneralFindingUpdate, user: AuthenticatedUser
    ) -> dict[str, Any]:
        """Patch a general finding."""

    def delete_general_finding(self, finding_id: str, user: AuthenticatedUser) -> dict[str, Any]:
        """Delete a general finding."""

    def get_project_conclusion(
        self, project_id: str, user_id: str
    ) -> Optional[dict[str, Any]]:
        """Return the project conclusion if present."""

    def upsert_project_conclusion(
        self, project_id: str, payload: ProjectConclusionUpsert, user: AuthenticatedUser
    ) -> dict[str, Any]:
        """Create or update the single project conclusion."""

    def delete_project_conclusion(self, project_id: str, user: AuthenticatedUser) -> dict[str, Any]:
        """Soft-delete the single project conclusion."""

    def start_ai_transcription(
        self, voice_note_id: str, user: AuthenticatedUser, ai_provider: AiProviderProtocol
    ) -> dict[str, Any]:
        """Run or retry an AI transcription job for a voice note."""

    def queue_ai_transcription(
        self, voice_note_id: str, user: AuthenticatedUser, ai_provider: AiProviderProtocol
    ) -> tuple[dict[str, Any], bool]:
        """Create or reuse an AI transcription job.

        The boolean indicates whether the returned job should be scheduled for processing.
        """

    def process_ai_transcription_job(
        self,
        job_id: str,
        voice_note_id: str,
        user: AuthenticatedUser,
        ai_provider: AiProviderProtocol,
    ) -> dict[str, Any]:
        """Process a queued AI transcription job and update related records."""

    def start_ai_image_description(
        self, media_asset_id: str, user: AuthenticatedUser, ai_provider: AiProviderProtocol
    ) -> dict[str, Any]:
        """Run or retry an AI image description job for a photo."""

    def get_ai_job(self, job_id: str, user_id: str) -> dict[str, Any]:
        """Return one visible AI job."""

    def report_preview(self, project_id: str, user_id: str) -> dict[str, Any]:
        """Return report preview data and warnings."""

    def confirm_report_preview(self, project_id: str, user: AuthenticatedUser) -> dict[str, Any]:
        """Store that a user confirmed the current report preview."""

    def generate_report(self, project_id: str, user: AuthenticatedUser) -> dict[str, Any]:
        """Generate a DOCX report version."""

    def list_report_versions(self, project_id: str, user_id: str) -> list[dict[str, Any]]:
        """List generated report versions."""

    def report_download_url(self, version_id: str, user: AuthenticatedUser) -> str:
        """Create a short-lived download URL for a report version."""

    def sync_pull(
        self, user_id: str, updated_since: Optional[datetime] = None
    ) -> dict[str, list[dict[str, Any]]]:
        """Return visible online state for the mobile sync cache."""

    def sync_push(
        self, operations: list[SyncOperation], user: AuthenticatedUser
    ) -> dict[str, list[dict[str, Any]]]:
        """Apply supported queued mobile operations."""
