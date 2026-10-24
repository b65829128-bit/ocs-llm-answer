from __future__ import annotations

import html
import json
import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher

CORRECT_HINTS = ("√", "✓")
INCORRECT_HINTS = ("×", "✗")
CORRECT_WORDS = ("正确", "对", "是", "true", "yes", "t", "1")
INCORRECT_WORDS = ("不正确", "不对", "不是", "错误", "错", "否", "false", "no", "f", "0", "非")


@dataclass(frozen=True)
class Option:
    label: str
    text: str
    raw: str


def clean_text(value: object) -> str:
    text = html.unescape(str(value or ""))
    text = text.replace("\u200b", "").replace("\ufeff", "").replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def normalize_for_match(value: object) -> str:
    text = unicodedata.normalize("NFKC", clean_text(value)).lower()
    return re.sub(r"[\W_]+", "", text, flags=re.UNICODE)


def judgement_value(value: object) -> str | None:
    raw = clean_text(value)
    if not raw:
        return None
    if any(hint in raw for hint in CORRECT_HINTS):
        return "对"
    if any(hint in raw for hint in INCORRECT_HINTS):
        return "错"
    text = normalize_for_match(raw)
    if not text:
        return None
    # 先判断否定，避免“不正确”被“正确”抢先命中
    if any(word in text for word in INCORRECT_WORDS):
        return "错"
    if any(word in text for word in CORRECT_WORDS):
        return "对"
    return None


def parse_options(raw_options: list[str]) -> list[Option]:
    options: list[Option] = []
    for index, raw in enumerate(raw_options):
        original = clean_text(raw)
        text = original
        # 去掉 A. / A、 / A) / A： / A- 等标签；字母统一按 DOM 顺序重排
        text = re.sub(r"^\s*[A-Za-z]\s*[\.\、\)\:：\-]\s*", "", text)
        text = re.sub(r"^\s*[A-Za-z]\s+(?=\S)", "", text)
        options.append(Option(label=chr(65 + index), text=clean_text(text), raw=original))
    return options


def is_judgement_options(options: list[Option]) -> bool:
    if len(options) != 2:
        return False
    values = [judgement_value(option.text) for option in options]
    return "对" in values and "错" in values


def infer_type(qtype: str, options: list[Option], question: str) -> str:
    qtype = (qtype or "unknown").strip().lower()
    if qtype in {"single", "multiple", "completion", "judgement"}:
        return qtype
    if not options:
        return "completion"
    if is_judgement_options(options):
        return "judgement"
    if re.search(r"多选|多项|至少.{0,6}(项|个)|全部.{0,4}(选|正确)", question):
        return "multiple"
    return "single"


def count_blanks(question: str) -> int:
    patterns = (r"_{2,}", r"（\s*）", r"\(\s*\)", r"【\s*】", r"\[\s*\]")
    return sum(len(re.findall(pattern, question)) for pattern in patterns)


def parse_letters(value: object, option_count: int) -> str | None:
    text = clean_text(value).upper()
    if not text or len(text) > 16:
        return None
    cleaned = re.sub(r"[\s,，、#;；/|.。:：\-()（）]+", "", text)
    if not cleaned or not re.fullmatch(r"[A-Z]+", cleaned):
        return None
    result: list[str] = []
    for char in cleaned:
        index = ord(char) - 65
        if index < 0 or index >= option_count:
            return None
        if char not in result:
            result.append(char)
    return "".join(sorted(result))


def match_option_index(answer: object, options: list[Option], threshold: float = 0.72) -> int | None:
    target = normalize_for_match(answer)
    if not target:
        return None
    for index, option in enumerate(options):
        if normalize_for_match(option.text) == target:
            return index
    contained: list[tuple[int, int]] = []
    for index, option in enumerate(options):
        candidate = normalize_for_match(option.text)
        if candidate and (candidate in target or target in candidate):
            contained.append((len(candidate), index))
    if contained:
        contained.sort(reverse=True)
        return contained[0][1]
    best_ratio = 0.0
    best_index: int | None = None
    for index, option in enumerate(options):
        candidate = normalize_for_match(option.text)
        if not candidate:
            continue
        ratio = SequenceMatcher(None, target, candidate).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best_index = index
    return best_index if best_ratio >= threshold else None


def stringify_answer(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (list, tuple)):
        return "#".join(str(item).strip() for item in value if str(item).strip())
    if isinstance(value, dict):
        return stringify_answer(value.get("answer"))
    return str(value).strip()


def coerce_answer(
    raw: object, options: list[Option], qtype: str, blank_count: int = 0
) -> tuple[str | None, str | None]:
    text = stringify_answer(raw)
    if not text:
        return None, "empty_answer"

    if qtype == "judgement" or (qtype == "single" and is_judgement_options(options)):
        value = judgement_value(text)
        if value:
            return value, None
        letters = parse_letters(text, len(options))
        if letters and len(letters) == 1:
            option = options[ord(letters) - 65]
            value = judgement_value(option.text)
            if value:
                return value, option.text
        for option in options:
            if normalize_for_match(option.text) == normalize_for_match(text):
                value = judgement_value(option.text)
                if value:
                    return value, option.text
        return None, "judgement_unmapped"

    if qtype == "single":
        match = re.search(r"(?:答案|选)\s*(?:是|为)?\s*[:：]?\s*([A-Z])\b", text.upper())
        if match:
            text = match.group(1)
        letters = parse_letters(text, len(options))
        if letters:
            return (letters[0], None) if len(letters) == 1 else (None, "multiple_letters_for_single")
        index = match_option_index(text, options)
        if index is None:
            return None, "option_not_matched"
        return chr(65 + index), options[index].text

    if qtype == "multiple":
        letters = parse_letters(text, len(options))
        if letters:
            return letters, None
        parts = [part for part in re.split(r"[#\n,，、;；/|]+", text) if part.strip()]
        if len(parts) > 1:
            indexes: list[int] = []
            for part in parts:
                index = match_option_index(part, options)
                if index is None:
                    return None, "option_not_matched"
                indexes.append(index)
            return "".join(chr(65 + index) for index in sorted(set(indexes))), None
        index = match_option_index(text, options)
        if index is None:
            return None, "option_not_matched"
        return chr(65 + index), options[index].text

    if qtype == "completion":
        text = re.sub(r"^(答案|答)\s*[:：]\s*", "", text).strip().strip("\"'")
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                text = "#".join(str(item).strip() for item in parsed if str(item).strip())
        except Exception:
            pass
        if "\n" in text:
            text = "#".join(part.strip() for part in text.splitlines() if part.strip())
        if blank_count > 1 and "#" not in text:
            parts = [part.strip() for part in re.split(r"[、，,；;]", text) if part.strip()]
            if len(parts) == blank_count:
                text = "#".join(parts)
        if normalize_for_match(text) in {"无法确定", "不确定", "无法判断", "不知道", "无法作答"}:
            return None, "uncertain"
        return (text or None), (None if text else "empty_answer")

    return None, "unknown_type"
