from functools import lru_cache
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Baudoku API"
    environment: str = "local"
    supabase_url: Optional[str] = None
    supabase_service_role_key: Optional[str] = None
    allowed_origins: str = "*"
    ai_enabled: bool = True
    ai_provider: str = "openai"
    openai_api_key: Optional[str] = None
    openai_transcription_model: str = "gpt-4o-transcribe"
    openai_text_model: str = "gpt-5.5"
    openai_vision_model: str = "gpt-5.5"
    ai_request_timeout_seconds: int = 60
    ai_max_retries: int = 2
    ai_prompt_version: str = "bba-ki-v1"
    ai_rate_limit_per_user_per_minute: int = 20
    gemini_api_key: Optional[str] = None
    gemini_text_model: str = "gemini-2.5-flash"
    bba_template_path: Optional[str] = None
    brevo_api_key: Optional[str] = None
    brevo_sender_email: Optional[str] = None
    brevo_sender_name: Optional[str] = None
    brevo_sandbox: bool = False
    brevo_max_inline_attachment_raw_bytes: int = 14_000_000
    brevo_link_expiry_seconds: int = 604_800
    brevo_timeout_seconds: int = 20

    model_config = SettingsConfigDict(
        env_file=(".env", ".env.local"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def is_supabase_configured(self) -> bool:
        return bool(self.supabase_url and self.supabase_service_role_key)

    @property
    def is_ai_configured(self) -> bool:
        if not self.ai_enabled:
            return False
        if self.ai_provider == "openai":
            return bool(self.openai_api_key)
        if self.ai_provider == "gemini":
            return bool(self.gemini_api_key)
        return False


@lru_cache
def get_settings() -> Settings:
    return Settings()
