from __future__ import annotations

import json

from .base import LLMResult


class MockProvider:
    """离线联调用：不请求外网，按题型返回固定答案。"""

    name = "mock"

    async def complete(self, messages, model, max_tokens, temperature) -> LLMResult:
        payload: dict = {}
        for message in reversed(messages):
            if message.get("role") != "user":
                continue
            content = message.get("content", "")
            if isinstance(content, list):
                text = "\n".join(
                    str(part.get("text", ""))
                    for part in content
                    if isinstance(part, dict) and part.get("type") == "text"
                )
            else:
                text = str(content)
            start = text.find("{")
            if start == -1:
                continue
            try:
                payload = json.loads(text[start:])
                break
            except json.JSONDecodeError:
                continue

        qtype = payload.get("type", "single")
        options = payload.get("options", [])
        if qtype == "multiple":
            answer = "AB" if len(options) >= 2 else "A"
        elif qtype == "judgement":
            answer = "对"
        elif qtype == "completion":
            answer = "示例答案"
        else:
            answer = "A"

        content = json.dumps({"answer": answer, "confidence": 0.99}, ensure_ascii=False)
        return LLMResult(content=content, model="mock", latency_ms=0)
