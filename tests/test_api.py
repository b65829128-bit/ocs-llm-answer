from dataclasses import replace

from fastapi.testclient import TestClient

from app.config import load_settings
from app.main import create_app


def make_client(tmp_path, **overrides):
    base = replace(
        load_settings(),
        provider="mock",
        db_path=tmp_path / "test.db",
        api_token="",
        cache_ttl_seconds=3600,
        min_confidence=0.35,
    )
    return TestClient(create_app(replace(base, **overrides)))


def test_health(tmp_path):
    client = make_client(tmp_path)
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["provider"] == "mock"


def test_single(tmp_path):
    client = make_client(tmp_path)
    response = client.post(
        "/api/answer",
        json={"question": "1+1=?", "options": ["A. 1", "B. 2"], "type": "single"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["ocs_format"][1] == "A"
    assert body["ocs_format"][2]["ai"] is True
    assert body["ocs_format"][2]["model"] == "mock"


def test_multiple(tmp_path):
    client = make_client(tmp_path)
    response = client.post(
        "/api/answer",
        json={
            "question": "以下哪些是编程语言？",
            "options": ["A. Python", "B. Java", "C. HTML"],
            "type": "multiple",
        },
    )
    body = response.json()
    assert body["success"] is True
    assert body["ocs_format"][1] == "AB"


def test_judgement(tmp_path):
    client = make_client(tmp_path)
    response = client.post(
        "/api/answer",
        json={"question": "地球是圆的。", "options": ["A. 对", "B. 错"], "type": "judgement"},
    )
    body = response.json()
    assert body["success"] is True
    assert body["ocs_format"][1] == "对"


def test_completion(tmp_path):
    client = make_client(tmp_path)
    response = client.post(
        "/api/answer",
        json={"question": "中国的首都是____。", "options": [], "type": "completion"},
    )
    body = response.json()
    assert body["success"] is True
    assert body["ocs_format"][1] == "示例答案"


def test_cache(tmp_path):
    client = make_client(tmp_path)
    payload = {"question": "1+1=?", "options": ["A. 1", "B. 2"], "type": "single"}
    first = client.post("/api/answer", json=payload).json()
    second = client.post("/api/answer", json=payload).json()
    assert first["cached"] is False
    assert second["cached"] is True
    assert second["ocs_format"][2]["server_cache"] is True


def test_image_cache_is_isolated_by_image_content(tmp_path):
    client = make_client(tmp_path)
    image_a = "data:image/png;base64,AAAA"
    image_b = "data:image/png;base64,BBBB"
    payload = {
        "question": "看图选择",
        "options": ["A. 猫", "B. 狗"],
        "type": "single",
        "images": [image_a],
    }
    first = client.post("/api/answer", json=payload).json()
    second = client.post("/api/answer", json=payload).json()
    changed = client.post("/api/answer", json={**payload, "images": [image_b]}).json()
    assert first["cached"] is False
    assert second["cached"] is True
    assert changed["cached"] is False
    assert first["ocs_format"][2]["images"] == 1


def test_low_confidence_returns_empty(tmp_path):
    client = make_client(tmp_path, min_confidence=1.0)
    response = client.post(
        "/api/answer",
        json={"question": "1+1=?", "options": ["A. 1", "B. 2"], "type": "single"},
    )
    body = response.json()
    assert body["success"] is True
    assert body["ocs_format"] == []
    assert body["reason"] == "low_confidence"


def test_auth(tmp_path):
    client = make_client(tmp_path, api_token="secret")
    payload = {"question": "1+1=?", "options": ["A. 1", "B. 2"], "type": "single"}
    assert client.post("/api/answer", json=payload).status_code == 401
    response = client.post("/api/answer", json=payload, headers={"Authorization": "Bearer secret"})
    assert response.status_code == 200
    assert response.json()["success"] is True


def test_empty_question(tmp_path):
    client = make_client(tmp_path)
    response = client.post("/api/answer", json={"question": "", "options": [], "type": "single"})
    body = response.json()
    assert response.status_code == 200
    assert body["success"] is False


def test_missing_key_returns_error(tmp_path):
    client = make_client(tmp_path, provider="deepseek", deepseek_api_key="")
    assert client.get("/health").json()["status"] == "missing_api_key"
    response = client.post(
        "/api/answer",
        json={"question": "1+1=?", "options": ["A. 1", "B. 2"], "type": "single"},
    )
    body = response.json()
    assert body["success"] is False
    assert "DEEPSEEK_API_KEY" in body["error"]


def test_string_options(tmp_path):
    client = make_client(tmp_path)
    response = client.post(
        "/api/answer",
        json={"question": "1+1=?", "options": "A. 1\nB. 2", "type": "single"},
    )
    body = response.json()
    assert body["success"] is True
    assert body["ocs_format"][1] == "A"


def test_stats(tmp_path):
    client = make_client(tmp_path)
    client.post(
        "/api/answer",
        json={"question": "1+1=?", "options": ["A. 1", "B. 2"], "type": "single"},
    )
    stats = client.get("/api/stats").json()
    assert stats["total_requests"] >= 1
