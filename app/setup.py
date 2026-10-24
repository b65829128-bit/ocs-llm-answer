from __future__ import annotations

import os
import shutil
import time
from pathlib import Path

import httpx
from dotenv import dotenv_values, set_key, unset_key

from . import __version__
from .config import ROOT_DIR, Settings
from .models import ConfigUpdate

LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}

OCS_DATA_HANDLERS = {
    "question": {"handler": "return (env) => env.suggestion_title || env.title || ''"},
    "options": {
        "handler": "return (env) => String(env.suggestion_options || env.options || '').split(String.fromCharCode(10)).filter(Boolean)"
    },
    "images": {"handler": "return (env) => Array.isArray(env.images) ? env.images : []"},
    "type": {"handler": "return (env) => env.type || 'unknown'"},
    "site": {
        "handler": "return () => { try { return location.host || ''; } catch (e) { return ''; } }"
    },
}

OCS_RESPONSE_HANDLER = (
    "return (res) => { if (!res) return []; "
    "if (res.success === false || res.detail) "
    "throw new Error(res.error || res.detail || 'LLM 答题失败'); "
    "return res.ocs_format || []; }"
)


def _saved_values(settings: Settings) -> dict:
    env_path = Path(settings.env_path)
    return dotenv_values(env_path) if env_path.exists() else {}


def public_config(settings: Settings) -> dict:
    env_exists = Path(settings.env_path).exists()
    saved = _saved_values(settings)
    runtime_key = bool(settings.deepseek_api_key)
    runtime_token = bool(settings.api_token)
    file_key = bool(saved.get("DEEPSEEK_API_KEY")) if env_exists else runtime_key
    file_token = bool(saved.get("API_TOKEN")) if env_exists else runtime_token
    return {
        "version": __version__,
        "host": settings.host,
        "port": settings.port,
        "provider": settings.provider,
        "base_url": settings.deepseek_base_url,
        "model": settings.deepseek_model,
        # 只把显式覆盖值返回给 UI；与默认模型相同时显示为空，避免误以为必须填写。
        "model_single": "" if settings.model_single == settings.deepseek_model else settings.model_single,
        "model_multiple": "" if settings.model_multiple == settings.deepseek_model else settings.model_multiple,
        "model_judgement": "" if settings.model_judgement == settings.deepseek_model else settings.model_judgement,
        "model_completion": "" if settings.model_completion == settings.deepseek_model else settings.model_completion,
        "thinking": settings.llm_thinking,
        "reasoning_effort": settings.llm_reasoning_effort,
        "timeout_seconds": settings.llm_timeout_seconds,
        "max_tokens": settings.llm_max_tokens,
        "temperature": settings.llm_temperature,
        "use_json_mode": settings.use_json_mode,
        "min_confidence": settings.min_confidence,
        "db_path": str(settings.db_path),
        "cache_ttl_seconds": settings.cache_ttl_seconds,
        "cors_origins": settings.cors_origins,
        "log_level": settings.log_level,
        # configured = .env 中已保存；loaded = 当前进程已加载。两者不同说明需要重启。
        "api_key_configured": file_key,
        "api_key_loaded": runtime_key,
        "api_token_configured": file_token,
        "api_token_loaded": runtime_token,
        "restart_pending": file_key != runtime_key or file_token != runtime_token,
        "env_file": str(settings.env_path),
    }


def save_config(settings: Settings, payload: ConfigUpdate) -> dict:
    env_path = Path(settings.env_path)
    env_path.parent.mkdir(parents=True, exist_ok=True)
    if not env_path.exists():
        template = ROOT_DIR / ".env.example"
        if template.exists() and template.resolve() != env_path.resolve():
            shutil.copyfile(template, env_path)
        else:
            env_path.write_text("# OCS LLM Answerer configuration\n", encoding="utf-8")

    values = {
        "HOST": payload.host,
        "PORT": str(payload.port),
        "LLM_PROVIDER": payload.provider,
        "DEEPSEEK_BASE_URL": payload.base_url,
        "DEEPSEEK_MODEL": payload.model,
        "MODEL_SINGLE": payload.model_single,
        "MODEL_MULTIPLE": payload.model_multiple,
        "MODEL_JUDGEMENT": payload.model_judgement,
        "MODEL_COMPLETION": payload.model_completion,
        "LLM_THINKING": "true" if payload.thinking else "false",
        "LLM_REASONING_EFFORT": payload.reasoning_effort,
        "LLM_TIMEOUT_SECONDS": f"{payload.timeout_seconds:g}",
        "LLM_MAX_TOKENS": str(payload.max_tokens),
        "LLM_TEMPERATURE": f"{payload.temperature:g}",
        "USE_JSON_MODE": "true" if payload.use_json_mode else "false",
        "MIN_CONFIDENCE": f"{payload.min_confidence:g}",
        "DB_PATH": payload.db_path,
        "CACHE_TTL_SECONDS": str(payload.cache_ttl_seconds),
        "CORS_ORIGINS": payload.cors_origins,
        "LOG_LEVEL": payload.log_level,
    }
    for key, value in values.items():
        set_key(str(env_path), key, value, quote_mode="always")

    if payload.clear_api_key:
        unset_key(str(env_path), "DEEPSEEK_API_KEY")
    elif payload.api_key:
        set_key(str(env_path), "DEEPSEEK_API_KEY", payload.api_key, quote_mode="always")

    if payload.clear_api_token:
        unset_key(str(env_path), "API_TOKEN")
    elif payload.api_token:
        set_key(str(env_path), "API_TOKEN", payload.api_token, quote_mode="always")

    try:
        os.chmod(env_path, 0o600)
    except OSError:
        pass

    saved = dotenv_values(env_path)
    return {
        "success": True,
        "env_file": str(env_path),
        "restart_required": True,
        "api_key_configured": bool(saved.get("DEEPSEEK_API_KEY")),
        "api_token_configured": bool(saved.get("API_TOKEN")),
    }


async def test_deepseek_connection(payload: ConfigUpdate, settings: Settings) -> dict:
    if payload.provider == "mock":
        return {
            "ok": True,
            "provider": "mock",
            "message": "mock 模式不请求外网，配置可直接保存。",
            "latency_ms": 0,
        }

    saved = _saved_values(settings)
    saved_key = str(saved.get("DEEPSEEK_API_KEY") or "").strip()
    runtime_key = settings.deepseek_api_key.strip()
    if payload.clear_api_key:
        api_key, key_source = "", "none"
    elif payload.api_key:
        api_key, key_source = payload.api_key.strip(), "form"
    elif saved_key and saved_key != runtime_key:
        # 页面保存后、进程重启前：优先测试刚写入 .env 的 Key。
        api_key, key_source = saved_key, "env_file"
    else:
        api_key, key_source = runtime_key, "runtime"
    if not api_key:
        return {"ok": False, "message": "尚未配置 DEEPSEEK_API_KEY。"}

    url = f"{payload.base_url.rstrip('/')}/chat/completions"
    body = {
        "model": payload.model,
        "messages": [{"role": "user", "content": "只回复 OK"}],
        "max_tokens": 16,
        "stream": False,
        "thinking": {"type": "disabled"},
        "temperature": 0,
    }
    timeout = min(20.0, max(3.0, float(payload.timeout_seconds)))
    started = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=min(10.0, timeout))) as client:
            response = await client.post(
                url,
                json=body,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            )
    except httpx.TimeoutException:
        return {"ok": False, "message": f"连接超时（>{timeout:.0f}s），请检查 Base URL 或网络。"}
    except httpx.HTTPError as exc:
        return {"ok": False, "message": f"连接失败：{exc}"}

    latency_ms = int((time.perf_counter() - started) * 1000)
    if response.status_code != 200:
        return {
            "ok": False,
            "status": response.status_code,
            "latency_ms": latency_ms,
            "message": f"DeepSeek 返回 HTTP {response.status_code}：{(response.text or '')[:300]}",
        }
    try:
        data = response.json()
    except Exception:
        return {"ok": False, "status": 200, "message": "响应不是合法 JSON。"}
    choices = data.get("choices") or []
    if not choices:
        return {"ok": False, "status": 200, "message": "响应中没有 choices。"}
    content = ((choices[0].get("message") or {}).get("content") or "").strip()
    message = "连接成功。" + (f" 模型回复：{content[:80]}" if content else "")
    if key_source == "env_file":
        message += " 使用的是 .env 中刚保存的 Key，重启服务后答题才会使用它。"
    return {
        "ok": True,
        "status": 200,
        "model": data.get("model") or payload.model,
        "latency_ms": latency_ms,
        "message": message,
        "key_source": key_source,
        "usage": data.get("usage") or {},
    }


def build_ocs_config(settings: Settings) -> list[dict]:
    host = settings.host
    if host in {"0.0.0.0", "::", "[::]"}:
        host = "127.0.0.1"
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    base = f"http://{host}:{settings.port}"
    headers = {"Content-Type": "application/json"}
    if settings.api_token:
        headers["Authorization"] = "Bearer YOUR_API_TOKEN"
    return [
        {
            "name": "本地 LLM (DeepSeek)",
            "homepage": f"{base}/setup",
            "url": f"{base}/api/answer",
            "method": "post",
            "type": "GM_xmlhttpRequest",
            "contentType": "json",
            "responseType": "json",
            "headers": headers,
            "data": OCS_DATA_HANDLERS,
            "handler": OCS_RESPONSE_HANDLER,
        }
    ]
