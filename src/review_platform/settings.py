"""Application configuration and deployment-independent security requirements."""

from __future__ import annotations

import secrets
from pathlib import Path
from typing import Literal
from urllib.parse import quote, urlsplit

from pydantic import AnyHttpUrl, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from review_platform.common.engine import EnginePoolSettings

LOCAL_FRONTEND_DEV_ORIGINS = ("http://localhost:5173", "http://localhost:5273")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="REVIEW_",
        env_file=".env",
        env_file_encoding="utf-8",
        dotenv_filtering="match_prefix",
        extra="forbid",
    )
    environment: Literal["development", "test", "production"] = "development"
    database_url: str | None = None
    migration_database_url: str | None = None
    dataset_path: Path = Path("fixtures/demo.sqlite")
    synthetic_import_enabled: bool = False
    synthetic_fixture_root: Path = Path("fixtures/dataset_contracts")
    source_render_storage_mode: Literal["disabled", "filesystem"] = "disabled"
    source_render_artifact_root: Path | None = None
    default_tenant_key: str = "demo"
    default_tenant_name: str = "Demo Workspace"
    max_global_admins: int | None = Field(default=None, ge=1, le=50)
    allowed_reviewer_domains: tuple[str, ...] = ()
    db_pool_size: int = Field(default=5, ge=1, le=100)
    db_max_overflow: int = Field(default=5, ge=0, le=100)
    db_pool_timeout: float = Field(default=30, gt=0)
    db_pool_recycle: int = Field(default=1800, ge=-1)
    session_hmac_key: SecretStr | None = None
    activation_hmac_key: SecretStr | None = None
    rate_limit_hmac_key: SecretStr | None = None
    audit_hmac_key: SecretStr | None = None
    allowed_origins: tuple[AnyHttpUrl, ...] = (AnyHttpUrl("https://localhost"),)
    allowed_hosts: tuple[str, ...] = ("localhost", "testserver")
    cookie_secure: bool = True
    session_absolute_seconds: int = Field(default=28800, ge=300)
    session_idle_seconds: int = Field(default=3600, ge=60)
    password_reset_ttl_seconds: int = Field(default=3600, ge=300)
    password_min_length: int = Field(default=12, ge=12)
    password_max_bytes: int = Field(default=1024, ge=64)
    auth_rate_window_seconds: int = Field(default=300, ge=10)
    global_role_max_seconds: int = Field(default=86400, ge=300)
    email_mode: Literal["console", "file", "smtp"] | None = None
    email_outbox_dir: Path = Path("var/email_outbox")
    email_from_address: str = "no-reply@review.local"
    email_smtp_host: str | None = None
    email_smtp_port: int = Field(default=587, ge=1, le=65535)
    email_smtp_username: str | None = None
    email_smtp_password: SecretStr | None = None
    email_smtp_use_tls: bool = True
    app_base_url: str = "https://localhost"
    password_reset_link_path: str = "/reset-password"
    support_contact: str | None = None

    @model_validator(mode="after")
    def validate_security(self) -> Settings:
        if self.session_idle_seconds > self.session_absolute_seconds:
            raise ValueError("idle session lifetime must not exceed absolute lifetime")
        keys = ("session_hmac_key", "activation_hmac_key", "rate_limit_hmac_key", "audit_hmac_key")
        if self.environment == "production":
            if self.synthetic_import_enabled:
                raise ValueError("synthetic imports are forbidden in production")
            if not self.database_url:
                raise ValueError("REVIEW_DATABASE_URL is required")
            if self.migration_database_url == self.database_url:
                raise ValueError("runtime and migration credentials must differ")
            if not self.cookie_secure:
                raise ValueError("secure cookies are required")
            if any(origin.scheme != "https" for origin in self.allowed_origins):
                raise ValueError("production origins require HTTPS")
            if urlsplit(self.app_base_url).scheme != "https":
                raise ValueError("production account links require HTTPS")
            if any(getattr(self, key) is None for key in keys):
                raise ValueError("explicit authentication HMAC keys are required")
            supplied = [getattr(self, key).get_secret_value() for key in keys]
            if len(set(supplied)) != len(keys):
                raise ValueError("authentication HMAC keys must be independent")
        for key in keys:
            value = getattr(self, key)
            if value is None:
                setattr(self, key, SecretStr(secrets.token_urlsafe(48)))
            elif len(value.get_secret_value()) < 32:
                raise ValueError("authentication HMAC keys must be at least 32 characters")
        if (
            self.source_render_storage_mode == "filesystem"
            and self.source_render_artifact_root is None
        ):
            raise ValueError("REVIEW_SOURCE_RENDER_ARTIFACT_ROOT is required")
        if self.environment != "production":
            self.allowed_hosts = tuple(
                dict.fromkeys((*self.allowed_hosts, "localhost", "127.0.0.1"))
            )
            extras = [
                AnyHttpUrl(origin)
                for origin in ("http://localhost:5173", "http://localhost:5273")
                if origin not in self.origin_strings
            ]
            self.allowed_origins = (*self.allowed_origins, *extras)
        return self

    @property
    def review_pool(self) -> EnginePoolSettings:
        return EnginePoolSettings(
            pool_size=self.db_pool_size,
            max_overflow=self.db_max_overflow,
            pool_timeout=self.db_pool_timeout,
            pool_recycle=self.db_pool_recycle,
        )

    @property
    def origin_strings(self) -> tuple[str, ...]:
        return tuple(str(origin).rstrip("/") for origin in self.allowed_origins)

    @property
    def expose_raw_account_tokens(self) -> bool:
        return self.environment != "production"

    def password_reset_link(self, raw_token: str) -> str:
        return (
            f"{self.app_base_url.rstrip('/')}{self.password_reset_link_path}"
            f"?reset_token={quote(raw_token, safe='')}"
        )


SESSION_COOKIE = "__Host-review_session"
CSRF_COOKIE = "__Host-review_csrf"
