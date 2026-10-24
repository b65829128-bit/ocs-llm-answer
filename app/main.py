from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse

from . import __version__
from .answer import (
    coerce_answer,
    count_blanks,
    clean_text,
    infer_type,
    parse_options,
    stringify_answer,
)
from .config import Settings, load_settings
from .models import AnswerRequest, ConfigUpdate
from .prompts import build_messages, parse_llm_json
from .providers import LLMError, build_provider, supports_vision
from .setup import build_ocs_config, public_config, save_config, test_deepseek_connection
from .storage import Storage

VERSION = __version__
PROMPT_VERSION = "prompt-v2"
STATIC_DIR = Path(__file__).resolve().parent / "static"
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
logger = logging.getLogger("ocs_llm")


def _supplied_token(authorization: str | None, x_api_token: str | None) -> str:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    if x_api_token:
        return x_api_token.strip()
    return ""


def _token_ok(settings: Settings, supplied: str) -> bool:
    return bool(settings.api_token and supplied and hmac.compare_digest(supplied, settings.api_token))


def _select_model(settings: Settings, qtype: str) -> str:
    mapping = {
        "single": settings.model_single,
        "multiple": settings.model_multiple,
        "judgement": settings.model_judgement,
        "completion": settings.model_completion,
    }
    return mapping.get(qtype, settings.deepseek_model)


def _image_digest(images: list[str]) -> str:
    if not images:
        return ""
    digest = hashlib.sha256()
    for image in images:
        digest.update(image.encode("utf-8"))
        digest.update(b"\x00")
    return digest.hexdigest()


def _cache_key(
    question: str,
    options,
    qtype: str,
    model: str,
    site: str | None,
    images: list[str],
    thinking: bool,
    reasoning_effort: str,
) -> str:
    payload = {
        "q": clean_text(question).lower(),
        "o": [clean_text(option.text).lower() for option in options],
        "t": qtype,
        "m": model,
        "s": site or "",
        "i": _image_digest(images),
        "think": f"{thinking}:{reasoning_effort}" if thinking else "off",
        "v": PROMPT_VERSION,
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _parse_confidence(value: object) -> float:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        confidence = 0.7
    return max(0.0, min(1.0, confidence))


def _error(message: str, request_id: str, started: float) -> dict:
    return {
        "success": False,
        "error": message,
        "ocs_format": [],
        "request_id": request_id,
        "latency_ms": int((time.perf_counter() - started) * 1000),
    }


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    storage = Storage(settings.db_path)
    provider = build_provider(settings)

    app = FastAPI(
        title="OCS LLM Answerer",
        description="Local LLM-backed answerer for OCS (AnswererWrapper protocol).",
        version=VERSION,
    )
    origins = [origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()] or ["*"]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.settings = settings
    app.state.storage = storage
    app.state.provider = provider

    async def require_token(
        authorization: str | None = Header(default=None),
        x_api_token: str | None = Header(default=None, alias="X-API-Token"),
    ) -> None:
        if not settings.api_token:
            return
        supplied = _supplied_token(authorization, x_api_token)
        if not _token_ok(settings, supplied):
            raise HTTPException(status_code=401, detail="invalid API token")

    async def require_admin(
        request: Request,
        authorization: str | None = Header(default=None),
        x_api_token: str | None = Header(default=None, alias="X-API-Token"),
    ) -> None:
        # 已设置 API_TOKEN 时，配置接口始终要求口令。
        if settings.api_token:
            supplied = _supplied_token(authorization, x_api_token)
            if not _token_ok(settings, supplied):
                raise HTTPException(status_code=401, detail="invalid API token")
            return

        # 未设置口令时，配置写入只允许本机访问，避免局域网/网页 CSRF 修改 .env。
        host = request.url.hostname or (request.client.host if request.client else "")
        if host not in LOCAL_HOSTS:
            raise HTTPException(
                status_code=403,
                detail="配置接口仅允许本机访问；如需远程配置，请先在 .env 设置 API_TOKEN。",
            )
        origin = request.headers.get("origin")
        if origin is not None:
            origin_host = urlparse(origin).hostname
            if not origin_host or origin_host not in LOCAL_HOSTS:
                raise HTTPException(status_code=403, detail="不允许跨站修改配置。")

    @app.get("/", include_in_schema=False)
    async def root():
        return RedirectResponse(url="/setup")

    @app.get("/config", include_in_schema=False)
    async def config_redirect():
        return RedirectResponse(url="/setup")

    @app.get("/setup", include_in_schema=False)
    async def setup_page():
        page = STATIC_DIR / "setup.html"
        if not page.exists():
            raise HTTPException(status_code=404, detail="setup page not found")
        return FileResponse(page, media_type="text/html", headers={"Cache-Control": "no-store"})

    @app.get("/api/config", dependencies=[Depends(require_admin)])
    async def get_config() -> dict:
        return public_config(settings)

    @app.post("/api/config/test", dependencies=[Depends(require_admin)])
    async def test_config(payload: ConfigUpdate) -> dict:
        return await test_deepseek_connection(payload, settings)

    @app.post("/api/config/save", dependencies=[Depends(require_admin)])
    async def save_config_route(payload: ConfigUpdate) -> dict:
        try:
            return await asyncio.to_thread(save_config, settings, payload)
        except Exception as exc:
            logger.exception("failed to save .env")
            raise HTTPException(status_code=500, detail=f"保存配置失败：{exc}") from exc

    @app.get("/api/ocs-config", dependencies=[Depends(require_admin)])
    async def get_ocs_config() -> dict:
        return {"config": build_ocs_config(settings)}

    @app.get("/health")
    async def health() -> dict:
        configured = provider.name == "mock" or bool(settings.deepseek_api_key)
        return {
            "status": "ok" if configured else "missing_api_key",
            "provider": provider.name,
            "model": settings.deepseek_model,
            "configured": configured,
            "thinking": settings.llm_thinking,
            "reasoning_effort": settings.llm_reasoning_effort,
            "vision": supports_vision(settings.deepseek_model),
            "version": VERSION,
        }

    @app.post("/api/answer")
    async def answer(req: AnswerRequest, _: None = Depends(require_token)) -> dict:
        started = time.perf_counter()
        request_id = uuid.uuid4().hex[:10]
        question = clean_text(req.question)
        if not question:
            return _error("question 为空", request_id, started)

        raw_options = req.options[:30]
        options = parse_options(raw_options)
        qtype = infer_type(req.type, options, question)
        if qtype in {"single", "multiple"} and not options:
            return _error("该题型需要选项，但 options 为空", request_id, started)

        blank_count = count_blanks(question) if qtype == "completion" else None
        model = _select_model(settings, qtype)
        images = [str(image).strip() for image in req.images if str(image).strip()]
        cache_key = _cache_key(
            question,
            options,
            qtype,
            model,
            req.site,
            images,
            settings.llm_thinking,
            settings.llm_reasoning_effort,
        )
        options_json = json.dumps([option.raw for option in options], ensure_ascii=False)[:12000]
        cached = await asyncio.to_thread(storage.get_cache, cache_key)
        if cached:
            latency_ms = int((time.perf_counter() - started) * 1000)
            confidence = _parse_confidence(cached.get("confidence"))
            extra = {
                "ai": True,
                "model": cached.get("model") or model,
                "confidence": round(confidence, 3),
                "latency_ms": latency_ms,
                "source": "llm",
                "server_cache": True,
                "thinking": settings.llm_thinking,
            }
            if settings.llm_thinking:
                extra["reasoning_effort"] = settings.llm_reasoning_effort
            if images:
                extra["images"] = len(images)
            if req.site:
                extra["site"] = req.site
            await asyncio.to_thread(
                storage.log,
                ts=int(time.time()),
                request_id=request_id,
                site=req.site,
                qtype=qtype,
                question=question[:5000],
                options_json=options_json,
                raw_answer=cached.get("answer"),
                answer=cached.get("answer"),
                confidence=confidence,
                model=cached.get("model") or model,
                latency_ms=latency_ms,
                cache_hit=1,
            )
            return {
                "success": True,
                "ocs_format": [question, cached.get("answer"), extra],
                "answer": cached.get("answer"),
                "confidence": round(confidence, 3),
                "model": cached.get("model") or model,
                "latency_ms": latency_ms,
                "cached": True,
                "request_id": request_id,
            }

        messages = build_messages(
            question=question,
            options=options,
            qtype=qtype,
            blank_count=blank_count,
            site=req.site,
            images=images,
            supports_vision=supports_vision(model),
        )
        try:
            result = await asyncio.wait_for(
                provider.complete(messages, model, settings.llm_max_tokens, settings.llm_temperature),
                timeout=settings.llm_timeout_seconds + 5,
            )
        except asyncio.TimeoutError:
            message = f"LLM 请求超时（>{settings.llm_timeout_seconds + 5:.0f}s）"
            logger.warning("%s request_id=%s", message, request_id)
            await asyncio.to_thread(
                storage.log,
                ts=int(time.time()),
                request_id=request_id,
                site=req.site,
                qtype=qtype,
                question=question[:5000],
                options_json=options_json,
                raw_answer=None,
                answer=None,
                confidence=None,
                model=model,
                latency_ms=int((time.perf_counter() - started) * 1000),
                error=message,
            )
            return _error(message, request_id, started)
        except LLMError as exc:
            message = str(exc)
            logger.warning("LLM error request_id=%s: %s", request_id, message)
            await asyncio.to_thread(
                storage.log,
                ts=int(time.time()),
                request_id=request_id,
                site=req.site,
                qtype=qtype,
                question=question[:5000],
                options_json=options_json,
                raw_answer=None,
                answer=None,
                confidence=None,
                model=model,
                latency_ms=int((time.perf_counter() - started) * 1000),
                error=message,
            )
            return _error(message, request_id, started)
        except Exception:
            logger.exception("unexpected error request_id=%s", request_id)
            return _error("服务内部错误", request_id, started)

        latency_ms = int((time.perf_counter() - started) * 1000)
        parsed = parse_llm_json(result.content)
        if not parsed:
            message = "无法解析模型输出"
            await asyncio.to_thread(
                storage.log,
                ts=int(time.time()),
                request_id=request_id,
                site=req.site,
                qtype=qtype,
                question=question[:5000],
                options_json=options_json,
                raw_answer=result.content[:2000],
                answer=None,
                confidence=None,
                model=result.model,
                latency_ms=latency_ms,
                prompt_tokens=result.prompt_tokens,
                completion_tokens=result.completion_tokens,
                error=message,
            )
            return _error(message, request_id, started)

        raw_answer = stringify_answer(parsed.get("answer"))
        confidence = _parse_confidence(parsed.get("confidence"))
        answer_text, reason = coerce_answer(raw_answer, options, qtype, blank_count or 0)

        if answer_text is None:
            await asyncio.to_thread(
                storage.log,
                ts=int(time.time()),
                request_id=request_id,
                site=req.site,
                qtype=qtype,
                question=question[:5000],
                options_json=options_json,
                raw_answer=raw_answer[:2000],
                answer=None,
                confidence=confidence,
                model=result.model,
                latency_ms=latency_ms,
                prompt_tokens=result.prompt_tokens,
                completion_tokens=result.completion_tokens,
                error=reason,
            )
            return {
                "success": True,
                "ocs_format": [],
                "answer": None,
                "confidence": round(confidence, 3),
                "model": result.model,
                "latency_ms": latency_ms,
                "reason": reason,
                "request_id": request_id,
            }

        if confidence < settings.min_confidence:
            await asyncio.to_thread(
                storage.log,
                ts=int(time.time()),
                request_id=request_id,
                site=req.site,
                qtype=qtype,
                question=question[:5000],
                options_json=options_json,
                raw_answer=raw_answer[:2000],
                answer=answer_text,
                confidence=confidence,
                model=result.model,
                latency_ms=latency_ms,
                prompt_tokens=result.prompt_tokens,
                completion_tokens=result.completion_tokens,
                error="low_confidence",
            )
            return {
                "success": True,
                "ocs_format": [],
                "answer": None,
                "confidence": round(confidence, 3),
                "model": result.model,
                "latency_ms": latency_ms,
                "reason": "low_confidence",
                "request_id": request_id,
            }

        extra = {
            "ai": True,
            "model": result.model,
            "confidence": round(confidence, 3),
            "latency_ms": latency_ms,
            "source": "llm",
            "thinking": settings.llm_thinking,
        }
        if settings.llm_thinking:
            extra["reasoning_effort"] = settings.llm_reasoning_effort
        if images:
            extra["images"] = len(images)
        if blank_count:
            extra["blank_count"] = blank_count
        if req.site:
            extra["site"] = req.site

        if settings.cache_ttl_seconds > 0:
            await asyncio.to_thread(
                storage.set_cache,
                cache_key,
                answer_text,
                confidence,
                result.model,
                settings.cache_ttl_seconds,
            )

        await asyncio.to_thread(
            storage.log,
            ts=int(time.time()),
            request_id=request_id,
            site=req.site,
            qtype=qtype,
            question=question[:5000],
            options_json=options_json,
            raw_answer=raw_answer[:2000],
            answer=answer_text,
            confidence=confidence,
            model=result.model,
            latency_ms=latency_ms,
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
        )
        return {
            "success": True,
            "ocs_format": [question, answer_text, extra],
            "answer": answer_text,
            "confidence": round(confidence, 3),
            "model": result.model,
            "latency_ms": latency_ms,
            "cached": False,
            "request_id": request_id,
        }

    @app.get("/api/stats")
    async def stats(_: None = Depends(require_token)) -> dict:
        return await asyncio.to_thread(storage.stats)

    @app.post("/api/cache/clear")
    async def clear_cache(_: None = Depends(require_token)) -> dict:
        deleted = await asyncio.to_thread(storage.clear_cache)
        return {"success": True, "deleted": deleted}

    return app


app = create_app()
