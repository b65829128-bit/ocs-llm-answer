from __future__ import annotations

import asyncio
import time

import httpx

from ..config import Settings
from .base import LLMError, LLMResult

RETRYABLE_STATUS = {429, 500, 502, 503, 504}


def supports_vision(model: str) -> bool:
    """DeepSeek V4.1 Flash is multimodal; V4 Pro is text-only."""
    name = (model or "").lower()
    return "flash" in name or "vision" in name


class DeepSeekProvider:
    name = "deepseek"

    def __init__(self, settings: Settings):
        self.settings = settings
        self.api_key = settings.deepseek_api_key
        self.url = f"{settings.deepseek_base_url}/chat/completions"
        self.timeout = settings.llm_timeout_seconds
        self.use_json_mode = settings.use_json_mode
        self.thinking = settings.llm_thinking
        self.reasoning_effort = settings.llm_reasoning_effort

    def _payload(self, messages, model: str, max_tokens: int, temperature: float) -> dict:
        payload: dict = {
            "model": model,
            "messages": messages,
            "stream": False,
            "max_tokens": max_tokens,
        }

        # 旧版 reasoner 永远处于思考模式，且不接受 temperature/response_format。
        # 保留这个分支只用于兼容用户显式配置的旧模型名。
        if "reasoner" in model.lower():
            return payload

        if self.thinking:
            payload["thinking"] = {"type": "enabled"}
            payload["reasoning_effort"] = self.reasoning_effort
            # 思考模式下 temperature 不生效，不发送以减少误解。
        else:
            payload["thinking"] = {"type": "disabled"}
            payload["temperature"] = temperature

        if self.use_json_mode:
            payload["response_format"] = {"type": "json_object"}
        return payload

    async def complete(self, messages, model, max_tokens, temperature) -> LLMResult:
        if not self.api_key:
            raise LLMError("DEEPSEEK_API_KEY 未配置，请在 .env 中填写后重启服务。")

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = self._payload(messages, model, max_tokens, temperature)
        started = time.perf_counter()
        feature_fallbacks = 0
        transient_retries = 0
        empty_retries = 0

        while True:
            try:
                async with httpx.AsyncClient(
                    timeout=httpx.Timeout(self.timeout, connect=min(10.0, self.timeout))
                ) as client:
                    response = await client.post(self.url, json=payload, headers=headers)
            except httpx.TimeoutException as exc:
                raise LLMError(f"DeepSeek 请求超时: {exc}") from exc
            except httpx.HTTPError as exc:
                if transient_retries < 1:
                    transient_retries += 1
                    await asyncio.sleep(0.5)
                    continue
                raise LLMError(f"DeepSeek 请求失败: {exc}") from exc
            except Exception as exc:
                raise LLMError(f"DeepSeek 响应解析失败: {exc}") from exc

            if response.status_code == 400:
                # 兼容旧模型或自建兼容端点：按特性降级重试，而不是直接失败。
                if "response_format" in payload and feature_fallbacks < 2:
                    payload.pop("response_format", None)
                    feature_fallbacks += 1
                    continue
                if ("thinking" in payload or "reasoning_effort" in payload) and feature_fallbacks < 2:
                    payload.pop("thinking", None)
                    payload.pop("reasoning_effort", None)
                    feature_fallbacks += 1
                    continue
                body = (response.text or "")[:300]
                raise LLMError(f"DeepSeek HTTP 400: {body}")

            if response.status_code in RETRYABLE_STATUS and transient_retries < 1:
                transient_retries += 1
                await asyncio.sleep(1.0)
                continue

            if response.status_code != 200:
                body = (response.text or "")[:300]
                raise LLMError(f"DeepSeek HTTP {response.status_code}: {body}")

            try:
                data = response.json()
            except Exception as exc:
                raise LLMError(f"DeepSeek 响应解析失败: {exc}") from exc

            choices = data.get("choices") or []
            if not choices:
                raise LLMError("DeepSeek 返回空 choices")
            choice = choices[0] or {}
            message = choice.get("message") or {}
            content = (message.get("content") or "").strip()
            if not content:
                # JSON Output 偶尔会返回空 content，重试一次。
                if empty_retries < 1:
                    empty_retries += 1
                    await asyncio.sleep(0.3)
                    continue
                raise LLMError("DeepSeek 返回空 content")

            if choice.get("finish_reason") == "length":
                raise LLMError(
                    "DeepSeek 输出被截断（finish_reason=length），请提高 LLM_MAX_TOKENS 或关闭思考模式。"
                )

            usage = data.get("usage") or {}
            latency_ms = int((time.perf_counter() - started) * 1000)
            return LLMResult(
                content=content,
                model=str(data.get("model") or model),
                prompt_tokens=int(usage.get("prompt_tokens") or 0),
                completion_tokens=int(usage.get("completion_tokens") or 0),
                latency_ms=latency_ms,
            )
