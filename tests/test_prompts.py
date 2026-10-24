from app.answer import parse_options
from app.prompts import FENCE, build_messages, normalize_image_url, parse_llm_json


def test_build_messages_attaches_images_for_vision_model():
    messages = build_messages(
        question="看图选择",
        options=parse_options(["A. 猫", "B. 狗"]),
        qtype="single",
        images=["data:image/png;base64,AAAA"],
        supports_vision=True,
    )
    assert messages[0]["role"] == "system"
    user = messages[1]
    assert isinstance(user["content"], list)
    parts = user["content"]
    assert parts[0]["type"] == "text"
    assert "image_count" in parts[0]["text"]
    assert parts[1] == {
        "type": "image_url",
        "image_url": {"url": "data:image/png;base64,AAAA", "detail": "high"},
    }


def test_build_messages_keeps_text_only_when_model_cannot_see_images():
    messages = build_messages(
        question="看图选择",
        options=parse_options(["A. 猫", "B. 狗"]),
        qtype="single",
        images=["data:image/png;base64,AAAA"],
        supports_vision=False,
    )
    user = messages[1]
    assert isinstance(user["content"], str)
    assert "image_count" in user["content"]
    assert "看不到图片" in user["content"]


def test_normalize_image_url_accepts_raw_base64():
    assert normalize_image_url("AAAA") == "data:image/png;base64,AAAA"
    assert normalize_image_url("https://example.com/a.png") == "https://example.com/a.png"
    assert normalize_image_url("") == ""


def test_parse_llm_json_accepts_object_fence_and_plain_string():
    assert parse_llm_json('{"answer":"B","confidence":0.9}')["answer"] == "B"
    fenced = FENCE + 'json\n{"answer":"A","confidence":0.8}\n' + FENCE
    assert parse_llm_json(fenced)["answer"] == "A"
    assert parse_llm_json('"C"')["answer"] == "C"
    assert parse_llm_json("答案是B")["answer"] == "答案是B"
