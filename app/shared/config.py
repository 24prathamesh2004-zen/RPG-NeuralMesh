"""Central configuration, read from .env through pydantic-settings. Only settings the mesh uses."""
from __future__ import annotations

from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


DEFAULT_ADMIN_EMAILS = "presenter@neuralmesh.local"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # ── App ────────────────────────────────────────────────────────────────────
    app_env: str = "development"
    app_secret_key: str = "change-me-development-only-32-bytes-minimum"  # development placeholder, refused in production
    log_level: str = "INFO"
    cors_allowed_origins: str = ""  # comma separated, needed outside development

    # ── Subsidiary nodes ───────────────────────────────────────────────────────
    neuralmesh_ceat_url: str = "http://127.0.0.1:8101/mcp"
    neuralmesh_kec_url: str = "http://127.0.0.1:8102/mcp"
    neuralmesh_zensar_url: str = "http://127.0.0.1:8103/mcp"
    neuralmesh_harrisons_url: str = "http://127.0.0.1:8104/mcp"
    neuralmesh_ceat_scope: str = ""
    neuralmesh_kec_scope: str = ""
    neuralmesh_zensar_scope: str = ""
    neuralmesh_harrisons_scope: str = ""

    # ── Models (which one each step uses is in config/model_policy.json) ──────
    neuralmesh_groq_api_key: str = ""
    neuralmesh_groq_model: str = "llama-3.3-70b-versatile"
    neuralmesh_anthropic_api_key: str = ""
    azure_openai_endpoint: str = ""
    azure_openai_api_key: str = ""
    azure_openai_deployment: str = "gpt-4.1-mini"
    azure_openai_api_version: str = "2025-01-01-preview"

    # ── Accounts, roles, tracing ───────────────────────────────────────────────
    neuralmesh_database_path: str = ".neuralmesh/accounts.db"
    neuralmesh_admin_emails: str = DEFAULT_ADMIN_EMAILS  # comma separated, the mesh_admin role in development
    neuralmesh_otel_endpoint: str = ""  # OTLP/HTTP traces endpoint, for example http://127.0.0.1:4318/v1/traces. Empty: no export
    neuralmesh_otel_headers: str = ""  # optional, "Authorization=Bearer x" pairs separated by commas

    @model_validator(mode="after")
    def _enforce_secret_key(self) -> "Settings":
        """Refuse to start in production with the default secret key."""
        if self.app_env == "production" and self.app_secret_key.startswith("change-me"):
            raise ValueError("app_secret_key must not be 'change-me' in production. Set APP_SECRET_KEY.")
        if self.app_env == "production" and DEFAULT_ADMIN_EMAILS in {e.strip().lower() for e in self.neuralmesh_admin_emails.split(",")}:
            raise ValueError("neuralmesh_admin_emails must not be the development default in production. Set NEURALMESH_ADMIN_EMAILS.")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
