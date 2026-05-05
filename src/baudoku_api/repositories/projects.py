from __future__ import annotations

from typing import Any, Optional

from baudoku_api.supabase_client import create_supabase_service_client

from baudoku_api.repositories.ai_operations import ProjectAiMixin
from baudoku_api.repositories.defect_media_operations import ProjectDefectMediaMixin
from baudoku_api.repositories.media_integrity import ProjectMediaIntegrityMixin
from baudoku_api.repositories.project_core import ProjectCoreMixin
from baudoku_api.repositories.project_helpers import (
    PROJECT_FILES_BUCKET,
    REPORT_TEMPLATE_VERSION,
    SYNC_ENTITY_TYPE_BY_OPERATION,
    SYNC_OPERATION_EVENT_TYPE,
    MediaUploadIntegrityError,
    ProjectNotFoundError,
    ProjectRepositoryError,
    SyncConflictError,
    _derive_project_status,
    _extension_for,
    _filter_projects,
    _now_iso,
    _plan_source_supports_image_render,
    _report_warnings,
    _response_data,
    _single_response_row,
    _text,
)
from baudoku_api.repositories.protocol import ProjectRepositoryProtocol
from baudoku_api.repositories.report_generation import ProjectReportMixin
from baudoku_api.repositories.repository_access import ProjectRepositoryAccessMixin
from baudoku_api.repositories.sync_operations import ProjectSyncMixin
from baudoku_api.repositories.workflow_operations import ProjectWorkflowMixin


class SupabaseProjectRepository(
    ProjectCoreMixin,
    ProjectDefectMediaMixin,
    ProjectWorkflowMixin,
    ProjectAiMixin,
    ProjectReportMixin,
    ProjectSyncMixin,
    ProjectMediaIntegrityMixin,
    ProjectRepositoryAccessMixin,
):
    def __init__(self) -> None:
        self._client_instance: Optional[Any] = None

    @property
    def _client(self) -> Any:
        if self._client_instance is None:
            self._client_instance = create_supabase_service_client()
        return self._client_instance


__all__ = [
    "PROJECT_FILES_BUCKET",
    "REPORT_TEMPLATE_VERSION",
    "SYNC_ENTITY_TYPE_BY_OPERATION",
    "SYNC_OPERATION_EVENT_TYPE",
    "MediaUploadIntegrityError",
    "ProjectNotFoundError",
    "ProjectRepositoryError",
    "ProjectRepositoryProtocol",
    "SupabaseProjectRepository",
    "SyncConflictError",
    "_derive_project_status",
    "_extension_for",
    "_filter_projects",
    "_now_iso",
    "_plan_source_supports_image_render",
    "_report_warnings",
    "_response_data",
    "_single_response_row",
    "_text",
]
