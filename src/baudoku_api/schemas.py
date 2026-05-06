from datetime import date, datetime
from typing import Any, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


AppraisalType = Literal[
    "Abnahmebegehung",
    "Schadensaufnahme",
    "Baubegleitung",
    "Maengelruege",
]

ProjectStatus = Literal[
    "Entwurf",
    "In Erfassung",
    "Bereit zur Pruefung",
    "Bericht generiert",
]

ProjectLanguage = Literal["de", "en"]
DefectKind = Literal["defect", "notice"]
AiStatus = Literal["open", "suggested", "edited", "confirmed", "error"]
MediaType = Literal["photo", "audio", "plan_source", "plan_render", "report_docx", "report_pdf"]
CaptionStatus = Literal["open", "suggested", "edited", "confirmed", "error"]
PlanFileType = Literal["jpg", "png", "pdf"]
PlanExportFormat = Literal["source", "image"]
VoiceTargetType = Literal["general_finding", "defect_description", "caption", "conclusion"]
TranscriptStatus = Literal["open", "suggested", "edited", "confirmed", "error"]
ReportTextStatus = Literal["draft", "confirmed"]
AiJobType = Literal["transcribe_audio", "describe_image"]
AiJobStatus = Literal["queued", "processing", "done", "failed"]


class ProjectCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    project_number: str = Field(min_length=1)
    client_name: str = Field(min_length=1)
    object_address: str = Field(min_length=1)
    site_visit_date: date
    appraisal_type: AppraisalType
    lead_user_id: Optional[UUID] = None
    language: ProjectLanguage = "de"
    client_id: Optional[str] = None


class ProjectUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    project_number: Optional[str] = Field(default=None, min_length=1)
    client_name: Optional[str] = Field(default=None, min_length=1)
    object_address: Optional[str] = Field(default=None, min_length=1)
    site_visit_date: Optional[date] = None
    appraisal_type: Optional[AppraisalType] = None
    lead_user_id: Optional[UUID] = None
    language: Optional[ProjectLanguage] = None
    client_id: Optional[str] = None


class ProjectRead(BaseModel):
    id: UUID
    project_number: str
    client_name: str
    object_address: str
    site_visit_date: date
    appraisal_type: AppraisalType
    lead_user_id: Optional[UUID] = None
    status: ProjectStatus
    language: ProjectLanguage
    created_by: UUID
    created_at: datetime
    updated_at: datetime
    deleted_at: Optional[datetime] = None
    revision: int
    report_revision: int = 0
    client_id: Optional[str] = None


class ProjectListResponse(BaseModel):
    items: list[ProjectRead]


class ProfileRead(BaseModel):
    id: UUID
    display_name: str
    email: str
    is_active: bool


class ProfileListResponse(BaseModel):
    items: list[ProfileRead]


class TradeRead(BaseModel):
    id: UUID
    name: str
    is_active: bool


class TradeListResponse(BaseModel):
    items: list[TradeRead]


class MediaInitUploadRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    media_type: MediaType
    mime_type: str = Field(min_length=1)
    file_name: Optional[str] = None
    client_id: Optional[str] = None
    media_id: Optional[UUID] = None
    storage_path: Optional[str] = Field(default=None, min_length=1)


class MediaInitUploadResponse(BaseModel):
    media_id: UUID
    storage_bucket: str
    storage_path: str
    upload_token: str
    signed_url: str


class MediaCompleteUploadRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    media_id: UUID
    media_type: MediaType
    storage_bucket: str = Field(min_length=1)
    storage_path: str = Field(min_length=1)
    mime_type: str = Field(min_length=1)
    file_size: Optional[int] = Field(default=None, ge=0)
    width: Optional[int] = Field(default=None, ge=0)
    height: Optional[int] = Field(default=None, ge=0)
    duration_seconds: Optional[float] = Field(default=None, ge=0)
    caption: Optional[str] = None
    client_id: Optional[str] = None


class MediaAssetRead(BaseModel):
    id: UUID
    project_id: UUID
    media_type: MediaType
    storage_bucket: str
    storage_path: str
    mime_type: str
    file_size: Optional[int] = None
    width: Optional[int] = None
    height: Optional[int] = None
    duration_seconds: Optional[float] = None
    caption: Optional[str] = None
    caption_status: CaptionStatus
    created_by: UUID
    created_at: datetime
    updated_at: Optional[datetime] = None
    deleted_at: Optional[datetime] = None
    revision: int = 1
    client_id: Optional[str] = None
    signed_url: Optional[str] = None


class MediaAssetListResponse(BaseModel):
    items: list[MediaAssetRead]


class MediaAssetUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    caption: Optional[str] = None
    caption_status: Optional[CaptionStatus] = None


class MediaSignedUrlResponse(BaseModel):
    media_asset_id: UUID
    signed_url: str
    expires_in_seconds: int = 600


class DefectCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    kind: DefectKind
    description: str = Field(min_length=1)
    local_label: str = Field(min_length=1)
    trade_id: Optional[UUID] = None
    trade_name_snapshot: Optional[str] = None
    category: Optional[str] = None
    client_id: Optional[str] = None


class DefectUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    kind: Optional[DefectKind] = None
    description: Optional[str] = Field(default=None, min_length=1)
    local_label: Optional[str] = Field(default=None, min_length=1)
    trade_id: Optional[UUID] = None
    trade_name_snapshot: Optional[str] = None
    category: Optional[str] = None
    report_sort_order: Optional[float] = None
    ai_status: Optional[AiStatus] = None
    client_id: Optional[str] = None


class DefectReorderRequest(BaseModel):
    defect_ids: list[UUID] = Field(min_length=1)


class DefectMediaLinkCreate(BaseModel):
    media_asset_id: UUID
    sort_order: float = 0
    include_in_report: bool = True
    client_id: Optional[str] = None


class DefectMediaLinkUpdate(BaseModel):
    defect_id: Optional[UUID] = None
    sort_order: Optional[float] = None
    include_in_report: Optional[bool] = None


class DefectMediaLinkRead(BaseModel):
    id: UUID
    defect_id: UUID
    media_asset_id: UUID
    sort_order: float
    include_in_report: bool
    created_at: datetime
    updated_at: Optional[datetime] = None
    deleted_at: Optional[datetime] = None
    revision: int = 1
    client_id: Optional[str] = None
    media_asset: Optional[MediaAssetRead] = None


class DefectRead(BaseModel):
    id: UUID
    project_id: UUID
    kind: DefectKind
    local_label: str
    report_number: Optional[int] = None
    report_sort_order: float
    trade_id: Optional[UUID] = None
    trade_name_snapshot: Optional[str] = None
    category: Optional[str] = None
    description: str
    ai_status: AiStatus
    created_by: UUID
    created_at: datetime
    updated_at: datetime
    deleted_at: Optional[datetime] = None
    revision: int
    client_id: Optional[str] = None
    media_links: list[DefectMediaLinkRead] = []


class DefectListResponse(BaseModel):
    items: list[DefectRead]


class PlanCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    media_asset_id: UUID
    name: str = Field(min_length=1)
    file_type: PlanFileType
    page_count: Optional[int] = Field(default=None, ge=1)
    selected_page: Optional[int] = Field(default=None, ge=1)
    client_id: Optional[str] = None


class PlanMarkerCreate(BaseModel):
    defect_id: UUID
    page_number: Optional[int] = Field(default=None, ge=1)
    x_norm: float = Field(ge=0, le=1)
    y_norm: float = Field(ge=0, le=1)
    label_override: Optional[str] = None
    client_id: Optional[str] = None


class PlanMarkerUpdate(BaseModel):
    defect_id: Optional[UUID] = None
    page_number: Optional[int] = Field(default=None, ge=1)
    x_norm: Optional[float] = Field(default=None, ge=0, le=1)
    y_norm: Optional[float] = Field(default=None, ge=0, le=1)
    label_override: Optional[str] = None
    client_id: Optional[str] = None


class PlanMarkerRead(BaseModel):
    id: UUID
    project_id: UUID
    plan_file_id: UUID
    defect_id: UUID
    page_number: Optional[int] = None
    x_norm: float
    y_norm: float
    label_override: Optional[str] = None
    created_by: UUID
    created_at: datetime
    updated_at: datetime
    deleted_at: Optional[datetime] = None
    revision: int = 1
    client_id: Optional[str] = None


class PlanRead(BaseModel):
    id: UUID
    project_id: UUID
    media_asset_id: UUID
    preview_media_asset_id: Optional[UUID] = None
    name: str
    file_type: PlanFileType
    page_count: Optional[int] = None
    selected_page: Optional[int] = None
    created_by: UUID
    created_at: datetime
    updated_at: Optional[datetime] = None
    deleted_at: Optional[datetime] = None
    revision: int = 1
    client_id: Optional[str] = None
    media_asset: Optional[MediaAssetRead] = None
    preview_media_asset: Optional[MediaAssetRead] = None
    markers: list[PlanMarkerRead] = []


class PlanListResponse(BaseModel):
    items: list[PlanRead]


class PlanExportRequest(BaseModel):
    format: PlanExportFormat = "source"


class PlanExportResponse(BaseModel):
    download_url: str
    file_name: str
    mime_type: str
    expires_in_seconds: int = 600


class VoiceNoteCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    media_asset_id: UUID
    target_type: VoiceTargetType
    defect_id: Optional[UUID] = None
    transcript: Optional[str] = None
    transcript_status: TranscriptStatus = "open"
    client_id: Optional[str] = None


class VoiceNoteUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    target_type: Optional[VoiceTargetType] = None
    defect_id: Optional[UUID] = None
    transcript: Optional[str] = None
    transcript_status: Optional[TranscriptStatus] = None
    client_id: Optional[str] = None


class VoiceNoteRead(BaseModel):
    id: UUID
    project_id: UUID
    media_asset_id: UUID
    defect_id: Optional[UUID] = None
    target_type: VoiceTargetType
    transcript: Optional[str] = None
    transcript_status: TranscriptStatus
    error_message: Optional[str] = None
    created_by: UUID
    created_at: datetime
    updated_at: datetime
    deleted_at: Optional[datetime] = None
    revision: int = 1
    client_id: Optional[str] = None
    media_asset: Optional[MediaAssetRead] = None


class VoiceNoteListResponse(BaseModel):
    items: list[VoiceNoteRead]


class GeneralFindingCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    text: str = ""
    source_voice_note_id: Optional[UUID] = None
    sort_order: Optional[float] = None
    status: ReportTextStatus = "draft"
    client_id: Optional[str] = None


class GeneralFindingUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    text: Optional[str] = None
    source_voice_note_id: Optional[UUID] = None
    sort_order: Optional[float] = None
    status: Optional[ReportTextStatus] = None
    client_id: Optional[str] = None


class GeneralFindingRead(BaseModel):
    id: UUID
    project_id: UUID
    text: str
    source_voice_note_id: Optional[UUID] = None
    sort_order: float
    status: ReportTextStatus
    created_by: UUID
    created_at: datetime
    updated_at: datetime
    deleted_at: Optional[datetime] = None
    revision: int = 1
    client_id: Optional[str] = None


class GeneralFindingListResponse(BaseModel):
    items: list[GeneralFindingRead]


class ProjectConclusionUpsert(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    text: str = ""
    source_voice_note_id: Optional[UUID] = None
    status: ReportTextStatus = "draft"
    client_id: Optional[str] = None


class ProjectConclusionRead(BaseModel):
    project_id: UUID
    text: str
    source_voice_note_id: Optional[UUID] = None
    status: ReportTextStatus
    updated_by: Optional[UUID] = None
    updated_at: datetime
    deleted_at: Optional[datetime] = None
    revision: int = 1
    client_id: Optional[str] = None


class AiJobRead(BaseModel):
    id: UUID
    project_id: UUID
    media_asset_id: Optional[UUID] = None
    job_type: AiJobType
    status: AiJobStatus
    provider: Optional[str] = None
    input_ref: Optional[str] = None
    result_text: Optional[str] = None
    error_message: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class AiTranscriptionRequest(BaseModel):
    voice_note_id: UUID


class AiImageDescriptionRequest(BaseModel):
    media_asset_id: UUID


class ReportWarning(BaseModel):
    code: str
    message: str
    severity: Literal["info", "warning"] = "warning"


class ReportPreviewResponse(BaseModel):
    project: ProjectRead
    defects: list[DefectRead]
    general_findings: list[GeneralFindingRead] = []
    project_conclusion: Optional[ProjectConclusionRead] = None
    voice_notes: list[VoiceNoteRead] = []
    plans: list[PlanRead] = []
    preview_confirmation: Optional["ReportPreviewConfirmationRead"] = None
    warnings: list[ReportWarning]


class ReportPreviewConfirmationRead(BaseModel):
    id: UUID
    project_id: UUID
    confirmed_by: UUID
    confirmed_at: datetime
    project_revision: int
    report_revision: int


class ReportGenerateResponse(BaseModel):
    version: "ReportVersionRead"
    warnings: list[ReportWarning]


class ReportVersionRead(BaseModel):
    id: UUID
    project_id: UUID
    version_number: int
    media_asset_id: UUID
    pdf_media_asset_id: Optional[UUID] = None
    generated_by: UUID
    generated_at: datetime
    warning_count: int
    warnings_snapshot: list[dict[str, Any]]
    template_version: Optional[str] = None
    report_revision: Optional[int] = None
    download_url: Optional[str] = None
    pdf_download_url: Optional[str] = None


class ReportVersionListResponse(BaseModel):
    items: list[ReportVersionRead]


class EmailRecipient(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    email: str = Field(min_length=3, max_length=320)
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        normalized = value.strip()
        if any(separator in normalized for separator in ("\r", "\n", ",", ";")):
            raise ValueError("E-Mail-Adresse ist ungueltig.")
        if "@" not in normalized or normalized.startswith("@") or normalized.endswith("@"):
            raise ValueError("E-Mail-Adresse ist ungueltig.")
        local_part, domain = normalized.rsplit("@", maxsplit=1)
        if not local_part or "." not in domain or domain.startswith(".") or domain.endswith("."):
            raise ValueError("E-Mail-Adresse ist ungueltig.")
        return normalized


class ReportEmailRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    to: list[EmailRecipient] = Field(min_length=1, max_length=99)
    cc: list[EmailRecipient] = Field(default_factory=list, max_length=99)
    bcc: list[EmailRecipient] = Field(default_factory=list, max_length=99)
    subject: str = Field(min_length=1, max_length=200)
    message: str = Field(min_length=1, max_length=20_000)
    client_send_id: Optional[str] = Field(default=None, min_length=1, max_length=120)

    @model_validator(mode="after")
    def validate_recipient_count(self) -> "ReportEmailRequest":
        recipient_count = len(self.to) + len(self.cc) + len(self.bcc)
        if recipient_count > 99:
            raise ValueError("Maximal 99 Empfaenger sind erlaubt.")
        return self


class ReportEmailResponse(BaseModel):
    message_id: str
    version_id: UUID
    sent_at: datetime
    recipient_count: int
    delivery_mode: Literal["attachments", "links"]
    attachment_bytes: int
    link_expires_at: Optional[datetime] = None


class SyncOperation(BaseModel):
    client_operation_id: Optional[str] = None
    type: str
    payload: dict[str, Any]


class SyncPushRequest(BaseModel):
    operations: list[SyncOperation] = []


class SyncPushResponse(BaseModel):
    applied: list[dict[str, Any]]
    rejected: list[dict[str, Any]]


class SyncPullResponse(BaseModel):
    projects: list[dict[str, Any]]
    defects: list[dict[str, Any]]
    media_assets: list[dict[str, Any]]
    defect_media_links: list[dict[str, Any]]
    plan_files: list[dict[str, Any]]
    plan_markers: list[dict[str, Any]]
    voice_notes: list[dict[str, Any]]
    general_findings: list[dict[str, Any]]
    project_conclusions: list[dict[str, Any]]
    tombstones: list["SyncTombstoneRead"] = []


class SyncTombstoneRead(BaseModel):
    entity_type: str
    entity_id: str
    project_id: Optional[str] = None
    deleted_at: datetime
    updated_at: Optional[datetime] = None
    revision: Optional[int] = None
