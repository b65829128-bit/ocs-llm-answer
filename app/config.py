from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / ".env")


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    host: str
    port: int
    provider: str
    deepseek_api_key: str
    deepseek_base_url: str
    deepseek_model: str
    model_single: str
    model_multiple: str
    model_judgement: str
    model_completion: str
    llm_timeout_seconds: float
    llm_max_tokens: int
    llm_temperature: float
    llm_thinking: bool
    llm_reasoning_effort: str
    min_confidence: float
    api_token: str
    db_path: Path
    cache_ttl_seconds: int
    cors_origins: str
    log_level: str
    use_json_mode: bool


def load_settings() -> Settings:
    default_model = os.getenv("DEEPSEEK_MODEL", "deepseek-flash").strip() or "deepseek-flash"
    raw_db_path = Path(os.getenv("DB_PATH", "data/ocs_llm.db")).expanduser()
    db_path = raw_db_path if raw_db_path.is_absolute() else ROOT_DIR / raw_db_path
    reasoning_effort = os.getenv("LLM_REASONING_EFFORT", "high").strip().lower() or "high"
    if reasoning_effort not in {"low", "high", "max"}:
        reasoning_effort = "high"
    return Settings(
        host=os.getenv("HOST", "127.0.0.1").strip() or "127.0.0.1",
        port=_env_int("PORT", 8787),
        provider=os.getenv("LLM_PROVIDER", "deepseek").strip().lower() or "deepseek",
        deepseek_api_key=os.getenv("DEEPSEEK_API_KEY", "").strip(),
        deepseek_base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/"),
        deepseek_model=default_model,
        model_single=os.getenv("MODEL_SINGLE", "").strip() or default_model,
        model_multiple=os.getenv("MODEL_MULTIPLE", "").strip() or default_model,
        model_judgement=os.getenv("MODEL_JUDGEMENT", "").strip() or default_model,
        model_completion=os.getenv("MODEL_COMPLETION", "").strip() or default_model,
        llm_timeout_seconds=_env_float("LLM_TIMEOUT_SECONDS", 45.0),
        llm_max_tokens=_env_int("LLM_MAX_TOKENS", 2048),
        llm_temperature=_env_float("LLM_TEMPERATURE", 0.0),
        llm_thinking=_env_bool("LLM_THINKING", False),
        llm_reasoning_effort=reasoning_effort,
        min_confidence=_env_float("MIN_CONFIDENCE", 0.35),
        api_token=os.getenv("API_TOKEN", "").strip(),
        db_path=db_path,
        cache_ttl_seconds=_env_int("CACHE_TTL_SECONDS", 7 * 24 * 3600),
        cors_origins=os.getenv("CORS_ORIGINS", "*").strip() or "*",
        log_level=os.getenv("LOG_LEVEL", "INFO").strip().upper() or "INFO",
        use_json_mode=_env_bool("USE_JSON_MODE", True),
    )
