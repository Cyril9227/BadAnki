import json

import pytest

from parsing import normalize_cards, robust_json_loads


def test_valid_json_keeps_real_newlines():
    """A schema-constrained provider encodes a line break as the JSON escape
    \\n. That must come back as a newline, not as literal backslash-n text."""
    raw = json.dumps({"cards": [{"question": "Q", "answer": "Step 1\nStep 2"}]})
    assert robust_json_loads(raw)["cards"][0]["answer"] == "Step 1\nStep 2"


def test_valid_json_keeps_escaped_latex_and_newlines_together():
    answer = "$$\\frac{a}{b}$$\n\n- item one\n- item two"
    raw = json.dumps({"cards": [{"question": "Q", "answer": answer}]})
    parsed = robust_json_loads(raw)
    assert parsed["cards"][0]["answer"] == answer
    # normalize_cards must not touch a correctly escaped document either.
    assert normalize_cards(parsed["cards"])[0]["answer"] == answer


def test_valid_json_without_math_keeps_tabs_and_newlines():
    raw = json.dumps({"cards": [{"question": "Q", "answer": "for x:\n\tprint(x)"}]})
    assert robust_json_loads(raw)["cards"][0]["answer"] == "for x:\n\tprint(x)"


def test_unescaped_latex_that_still_parses_is_repaired():
    """A raw \\frac inside a JSON string decodes as form-feed + "rac". No
    escaped backslash anywhere plus math delimiters marks it as broken LaTeX,
    so the repair path runs and restores the command."""
    raw = '{"cards": [{"question": "Q", "answer": "$\\frac{1}{2}$"}]}'
    assert robust_json_loads(raw)["cards"][0]["answer"] == "$\\frac{1}{2}$"


def test_invalid_json_from_unescaped_latex_is_repaired():
    # "\a" is not a JSON escape at all, so json.loads fails outright.
    raw = '{"cards": [{"question": "Q", "answer": "$\\alpha + \\beta$"}]}'
    assert robust_json_loads(raw)["cards"][0]["answer"] == "$\\alpha + \\beta$"


def test_code_fences_are_stripped():
    raw = "```json\n" + json.dumps({"cards": []}) + "\n```"
    assert robust_json_loads(raw) == {"cards": []}


def test_garbage_still_raises():
    with pytest.raises(json.JSONDecodeError):
        robust_json_loads("not json at all")
