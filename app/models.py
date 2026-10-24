from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


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
