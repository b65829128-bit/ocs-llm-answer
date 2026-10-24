from dataclasses import replace
from pathlib import Path

from dotenv import dotenv_values
from fastapi.testclient import TestClient

from app.config import load_settings
from app.main import create_app

HEADERS = {"Authorization": "Bearer secret"}


def make_client(tmp_path: Path, **overrides):
    base = replace(
        load_settings(),
        provider="mock",
        db_path=tmp_path / "test.db",
        env_path=tmp_path / ".env",
        api_token="secret",
        cache_ttl_seconds=3600,
        min_confidence=0.35,
    )
    return TestClient(create_app(replace(base, **overrides)))


def test_setup_page_and_redirects(tmp_path):
    client = make_client(tmp_path)
    page = client.get("/setup")
    assert page.status_code == 200
    assert "配置你的本地答题器" in page.text

    root = client.get("/", follow_redirects=False)
    assert root.status_code in {302, 307}
    assert root.headers["location"] == "/setup"

    config = client.get("/config", follow_redirects=False)
    assert config.status_code in {302, 307}
    assert config.headers["location"] == "/setup"


def test_config_requires_token_and_redacts_secrets(tmp_path):
    client = make_client(tmp_path, deepseek_api_key="sk-do-not-leak")
    assert client.get("/api/config").status_code == 401

    response = client.get("/api/config", headers=HEADERS)
    assert response.status_code == 200
    body = response.json()
    assert body["api_key_configured"] is True
    assert body["api_token_configured"] is True
    assert body["model"] == "deepseek-flash"
    assert body["model_single"] == ""
    assert body["env_file"].endswith(".env")
    assert "sk-do-not-leak" not in response.text


def test_config_requires_local_or_token(tmp_path):
    client = make_client(tmp_path, api_token="")
    response = client.get("/api/config")
    assert response.status_code == 403
    assert "本机" in response.json()["detail"]


def test_test_connection_mock(tmp_path):
    client = make_client(tmp_path)
    response = client.post("/api/config/test", json={"provider": "mock"}, headers=HEADERS)
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["provider"] == "mock"


def test_test_connection_requires_key_for_deepseek(tmp_path):
    client = make_client(tmp_path, deepseek_api_key="")
    response = client.post(
        "/api/config/test",
        headers=HEADERS,
        json={"provider": "deepseek", "base_url": "https://api.deepseek.com", "model": "deepseek-flash"},
    )
    assert response.status_code == 200
    assert response.json()["ok"] is False
    assert "DEEPSEEK_API_KEY" in response.json()["message"]


def test_save_config_writes_env(tmp_path):
    client = make_client(tmp_path)
    response = client.post(
        "/api/config/save",
        headers=HEADERS,
        json={
            "provider": "mock",
            "host": "127.0.0.1",
            "port": 8787,
            "model": "deepseek-flash",
            "api_key": "sk-new-key",
            "api_token": "new-token",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["restart_required"] is True
    assert body["api_key_configured"] is True
    assert body["api_token_configured"] is True
    env_file = Path(body["env_file"])
    assert env_file.exists()
    text = env_file.read_text(encoding="utf-8")
    assert "sk-new-key" in text
    assert "new-token" in text
    assert "LLM_PROVIDER" in text
    assert "DEEPSEEK_MODEL" in text
    values = dotenv_values(env_file)
    assert values["DEEPSEEK_API_KEY"] == "sk-new-key"
    assert values["API_TOKEN"] == "new-token"
    assert values["LLM_PROVIDER"] == "mock"


def test_save_config_keeps_blank_secrets(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "DEEPSEEK_API_KEY='old-key'\nAPI_TOKEN='secret'\n",
        encoding="utf-8",
    )
    client = make_client(tmp_path, deepseek_api_key="old-key", api_token="secret")
    response = client.post(
        "/api/config/save",
        headers=HEADERS,
        json={"provider": "mock", "api_key": "", "api_token": ""},
    )
    assert response.status_code == 200
    text = env_file.read_text(encoding="utf-8")
    assert "old-key" in text
    assert "secret" in text


def test_ocs_config_generation(tmp_path):
    client = make_client(tmp_path)
    response = client.get("/api/ocs-config", headers=HEADERS)
    assert response.status_code == 200
    wrapper = response.json()["config"][0]
    assert wrapper["url"] == "http://127.0.0.1:8787/api/answer"
    assert wrapper["type"] == "GM_xmlhttpRequest"
    assert "env.images" in wrapper["data"]["images"]["handler"]
    assert "YOUR_API_TOKEN" in wrapper["headers"]["Authorization"]
