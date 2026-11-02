"""Central configuration — reads from .env via pydantic-settings.

Secrets that live in Azure Key Vault are declared as ``*_kv_uri`` fields.
The ``_resolve_kv_secrets`` validator fetches the real values at startup so the
rest of the app reads plain fields (e.g. ``settings.azure_openai_api_key``) with
no knowledge of Key Vault.

This is the accelerator baseline — add app-specific settings in the
"App-specific settings" block at the bottom; keep the platform blocks intact.
"""
from __future__ import annotations

from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # ── App ────────────────────────────────────────────────────────────────────
    app_env: str = "development"
    app_secret_key: str = "change-me"
    log_level: str = "INFO"
    # Comma-separated allowed origins for non-development environments, e.g.
    # "https://__APP_NAME__-fe.bravesky-d9f9eeb7.eastus2.azurecontainerapps.io"
    cors_allowed_origins: str = ""

    # ── Database / Cache ───────────────────────────────────────────────────────
    database_url: str = "postgresql+asyncpg://postgres:password@localhost:5432/__DB_NAME__"
    redis_url: str = "redis://localhost:6379/0"

    # ── Azure OpenAI ───────────────────────────────────────────────────────────
    azure_openai_endpoint: str = ""
    azure_openai_api_key: str = ""
    azure_openai_deployment: str = "gpt-4.1-mini"
    azure_openai_embedding_deployment: str = "text-embedding-3-small"
    azure_openai_api_version: str = "2025-01-01-preview"

    # ── Azure Key Vault ────────────────────────────────────────────────────────
    azure_keyvault_url: str = "https://zaf-kv-01.vault.azure.net/"

    # KV URI overrides — when set, the corresponding plain field is populated at
    # startup by _resolve_kv_secrets below.
    azure_openai_endpoint_kv_uri: str = ""
    azure_openai_api_key_kv_uri: str = ""
    azure_openai_deployment_kv_uri: str = ""
    database_url_kv_uri: str = ""
    redis_url_kv_uri: str = ""

    # ── Azure / EntraID ────────────────────────────────────────────────────────
    azure_tenant_id: str = ""
    azure_client_id: str = ""
    azure_client_secret: str = ""
    azure_client_secret_kv_uri: str = ""
    entra_authority: str = "https://login.microsoftonline.com/"
    entra_audience: str = ""

    # ── RPG NeuralMesh subsidiary MCP endpoints ───────────────────────────────
    neuralmesh_ceat_url: str = "http://127.0.0.1:8101/mcp"
    neuralmesh_kec_url: str = "http://127.0.0.1:8102/mcp"
    neuralmesh_zensar_url: str = "http://127.0.0.1:8103/mcp"
    neuralmesh_harrisons_url: str = "http://127.0.0.1:8104/mcp"
    neuralmesh_ceat_scope: str = ""
    neuralmesh_kec_scope: str = ""
    neuralmesh_zensar_scope: str = ""
    neuralmesh_harrisons_scope: str = ""
    neuralmesh_groq_api_key: str = ""
    neuralmesh_groq_model: str = "llama-3.3-70b-versatile"
    neuralmesh_database_path: str = ".neuralmesh/accounts.db"

    # ── Vector DB (optional) ───────────────────────────────────────────────────
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: str = ""

    # ── Temporal ───────────────────────────────────────────────────────────────
    temporal_host: str = "localhost:7233"
    temporal_namespace: str = "__NAMESPACE__"
    temporal_task_queue_agents: str = "__TASK_QUEUE__"

    # ── Arize Phoenix Observability ────────────────────────────────────────────
    phoenix_host: str = "localhost"
    phoenix_port: int = 6006
    # e.g. https://zaf-phoenix.bravesky-d9f9eeb7.eastus2.azurecontainerapps.io/v1/traces
    phoenix_collector_endpoint: str = ""
    phoenix_project_name: str = "__APP_NAME__"
    arize_phoenix_api_key: str = ""          # resolved from KV
    arize_phoenix_api_key_kv_uri: str = ""

    # ── Prompts ────────────────────────────────────────────────────────────────
    prompts_dir: str = "config/prompts"

    # ────────────────────────────────────────────────────────────────────────────
    # App-specific settings — add your own fields below (external APIs, feature
    # flags, thresholds, etc). Declare a matching ``*_kv_uri`` and add it to the
    # kv_map in _resolve_kv_secrets for any secret sourced from Key Vault.
    # ────────────────────────────────────────────────────────────────────────────

    # ── Security validators ────────────────────────────────────────────────────
    @model_validator(mode="after")
    def _enforce_secret_key(self) -> "Settings":
        """Refuse to start in production with the default secret key."""
        if self.app_env == "production" and self.app_secret_key == "change-me":
            raise ValueError(
                "app_secret_key must not be 'change-me' in production. "
                "Set APP_SECRET_KEY via Azure Key Vault or an environment variable."
            )
        return self

    @model_validator(mode="after")
    def _resolve_kv_secrets(self) -> "Settings":
        """Replace any field whose corresponding ``*_kv_uri`` is set with the
        secret value fetched from Azure Key Vault. Silent no-op when the Azure
        SDK is not installed (local dev)."""
        try:
            from security.vault import get_secret_by_uri
        except ImportError:
            return self

        kv_map: list[tuple[str, str]] = [
            ("azure_openai_endpoint_kv_uri", "azure_openai_endpoint"),
            ("azure_openai_api_key_kv_uri", "azure_openai_api_key"),
            ("azure_openai_deployment_kv_uri", "azure_openai_deployment"),
            ("database_url_kv_uri", "database_url"),
            ("redis_url_kv_uri", "redis_url"),
            ("arize_phoenix_api_key_kv_uri", "arize_phoenix_api_key"),
            ("azure_client_secret_kv_uri", "azure_client_secret"),
        ]
        for uri_field, target_field in kv_map:
            uri: str = getattr(self, uri_field, "")
            if uri:
                value = get_secret_by_uri(uri)
                if value:
                    object.__setattr__(self, target_field, value)
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
