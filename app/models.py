from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class AnswerRequest(BaseModel):
    question: str = Field(default="", max_length=20000)
    options: list[str] = Field(default_factory=list)
    type: str = Field(default="unknown", max_length=32)
    images: list[str] = Field(default_factory=list)
    site: str | None = Field(default=None, max_length=200)

    @field_validator("options", mode="before")
    @classmethod
    def _options_to_list(cls, value):
        if value is None:
            return []
        if isinstance(value, str):
            return [line.strip() for line in value.replace("\r\n", "\n").split("\n") if line.strip()]
        if isinstance(value, (list, tuple)):
            return [str(item).strip() for item in value if str(item).strip()]
        return value

    @field_validator("type", mode="before")
    @classmethod
    def _normalize_type(cls, value):
        return str(value or "unknown").strip().lower()

    @field_validator("images", mode="before")
    @classmethod
    def _images_to_list(cls, value):
        if value is None:
            return []
        if isinstance(value, str):
            value = [value]
        if isinstance(value, (list, tuple)):
            return [str(item).strip() for item in value if str(item).strip()]
        return value


class ConfigUpdate(BaseModel):
    """WebUI 提交的完整运行配置。"""

    host: str = Field(default="127.0.0.1", min_length=1, max_length=255)
    port: int = Field(default=8787, ge=1, le=65535)
    provider: Literal["deepseek", "mock"] = "deepseek"

    api_key: str = Field(default="", max_length=500)
    clear_api_key: bool = False
    base_url: str = Field(default="https://api.deepseek.com", min_length=1, max_length=500)
    model: str = Field(default="deepseek-flash", min_length=1, max_length=100)
    model_single: str = Field(default="", max_length=100)
    model_multiple: str = Field(default="", max_length=100)
    model_judgement: str = Field(default="", max_length=100)
    model_completion: str = Field(default="", max_length=100)

    thinking: bool = False
    reasoning_effort: Literal["low", "high", "max"] = "high"
    timeout_seconds: float = Field(default=45, ge=1, le=300)
    max_tokens: int = Field(default=2048, ge=1, le=393216)
    temperature: float = Field(default=0, ge=0, le=2)
    use_json_mode: bool = True
    min_confidence: float = Field(default=0.35, ge=0, le=1)

    api_token: str = Field(default="", max_length=500)
    clear_api_token: bool = False
    db_path: str = Field(default="data/ocs_llm.db", min_length=1, max_length=500)
    cache_ttl_seconds: int = Field(default=604800, ge=0)
    cors_origins: str = Field(default="*", max_length=1000)
    log_level: str = Field(default="INFO", max_length=20)

    @field_validator("host", "model", "db_path")
    @classmethod
    def _strip_required(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("不能为空")
        return value

    @field_validator("base_url")
    @classmethod
    def _validate_base_url(cls, value: str) -> str:
        value = value.strip().rstrip("/")
        if not value.startswith(("http://", "https://")):
            raise ValueError("Base URL 必须以 http:// 或 https:// 开头")
        return value

    @field_validator("api_key", "api_token", "cors_origins")
    @classmethod
    def _strip_optional(cls, value: str) -> str:
        return value.strip()

    @field_validator("model_single", "model_multiple", "model_judgement", "model_completion")
    @classmethod
    def _strip_model(cls, value: str) -> str:
        return value.strip()

    @field_validator("log_level")
    @classmethod
    def _normalize_log_level(cls, value: str) -> str:
        value = value.strip().upper()
        return value or "INFO"

    @model_validator(mode="after")
    def _validate_secret_reset(self):
        if self.clear_api_key and self.api_key:
            raise ValueError("不能同时填写新 API Key 和勾选“清除已保存 Key”")
        if self.clear_api_token and self.api_token:
            raise ValueError("不能同时填写新 API Token 和勾选“清除已保存 Token”")
        return self
