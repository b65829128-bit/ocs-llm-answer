from dataclasses import replace

from app.config import load_settings
from app.providers.deepseek import DeepSeekProvider, supports_vision


def provider(**overrides):
    base = {
        "provider": "deepseek",
        "deepseek_api_key": "test-key",
        "deepseek_model": "deepseek-flash",
        "llm_thinking": False,
        "llm_reasoning_effort": "high",
        "use_json_mode": True,
    }
    base.update(overrides)
    return DeepSeekProvider(replace(load_settings(), **base))


def test_non_thinking_payload_uses_temperature_and_json_mode():
    payload = provider()._payload([], "deepseek-flash", 2048, 0.0)
    assert payload["thinking"] == {"type": "disabled"}
    assert payload["temperature"] == 0.0
    assert payload["response_format"] == {"type": "json_object"}
    assert "reasoning_effort" not in payload


def test_thinking_payload_uses_effort_and_omits_temperature():
    payload = provider(llm_thinking=True, llm_reasoning_effort="max")._payload(
        [], "deepseek-flash", 4096, 0.0
    )
    assert payload["thinking"] == {"type": "enabled"}
    assert payload["reasoning_effort"] == "max"
    assert "temperature" not in payload
    assert payload["response_format"] == {"type": "json_object"}


def test_legacy_reasoner_payload_is_kept_minimal():
    payload = provider(llm_thinking=True)._payload([], "deepseek-reasoner", 2048, 0.0)
    assert "thinking" not in payload
    assert "reasoning_effort" not in payload
    assert "temperature" not in payload
    assert "response_format" not in payload


def test_vision_capability_by_model():
    assert supports_vision("deepseek-flash")
    assert supports_vision("deepseek-v4-flash")
    assert supports_vision("deepseek-v4-flash-vision-exp")
    assert not supports_vision("deepseek-v4-pro")
