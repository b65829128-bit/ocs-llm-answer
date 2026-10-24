from app.answer import (
    coerce_answer,
    count_blanks,
    infer_type,
    is_judgement_options,
    judgement_value,
    parse_options,
)


def opts(*values):
    return parse_options(list(values))


def test_parse_options_strips_labels_and_reindexes():
    options = opts("B. 选项一", "A、选项二", "选项三")
    assert [option.label for option in options] == ["A", "B", "C"]
    assert [option.text for option in options] == ["选项一", "选项二", "选项三"]


def test_single_letter_and_text():
    options = opts("A. 1", "B、2", "C) 3")
    assert coerce_answer("B", options, "single")[0] == "B"
    assert coerce_answer("2", options, "single")[0] == "B"
    assert coerce_answer("B. 2", options, "single")[0] == "B"
    assert coerce_answer("答案是B", options, "single")[0] == "B"
    assert coerce_answer("C", options, "single")[0] == "C"


def test_multiple_letters_and_text():
    options = opts("A. 选项一", "B. 选项二", "C. 选项三")
    assert coerce_answer("AC", options, "multiple")[0] == "AC"
    assert coerce_answer("A、C", options, "multiple")[0] == "AC"
    assert coerce_answer("选项一#选项三", options, "multiple")[0] == "AC"
    assert coerce_answer("A#C#A", options, "multiple")[0] == "AC"


def test_judgement():
    options = opts("A. 对", "B. 错")
    assert is_judgement_options(options)
    assert coerce_answer("对", options, "judgement")[0] == "对"
    assert coerce_answer("B", options, "judgement")[0] == "错"
    assert coerce_answer("不正确", options, "judgement")[0] == "错"
    assert coerce_answer("正确", options, "judgement")[0] == "对"
    assert coerce_answer("×", options, "judgement")[0] == "错"
    assert judgement_value("√") == "对"


def test_single_with_judgement_options():
    options = opts("A. 正确", "B. 错误")
    assert coerce_answer("B", options, "single")[0] == "错"


def test_completion():
    assert coerce_answer("北京", [], "completion")[0] == "北京"
    assert coerce_answer("答案：北京", [], "completion")[0] == "北京"
    assert coerce_answer("北京#上海", [], "completion")[0] == "北京#上海"
    assert coerce_answer(["北京", "上海"], [], "completion")[0] == "北京#上海"
    assert coerce_answer("北京\n上海", [], "completion")[0] == "北京#上海"
    assert coerce_answer("北京、上海", [], "completion", 2)[0] == "北京#上海"
    assert coerce_answer("北京，上海", [], "completion", 2)[0] == "北京#上海"
    assert coerce_answer("无法确定", [], "completion")[0] is None


def test_infer_type_and_blanks():
    assert infer_type("unknown", opts("A. 对", "B. 错"), "") == "judgement"
    assert infer_type("unknown", [], "填空____") == "completion"
    assert infer_type("unknown", opts("A. 1", "B. 2"), "这是多选题，至少两项") == "multiple"
    assert infer_type("unknown", opts("A. 1", "B. 2"), "这是单选题") == "single"
    assert count_blanks("中国的首都是____，最大的城市是____。") == 2
