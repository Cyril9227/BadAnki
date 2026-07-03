# Unit tests for Telegram card formatting (pure functions, no DB required).

import telegram_format
from telegram_format import needs_screenshot, render_markdown_v2, spoiler_safe
from bot import (
    _answer_cache_key,
    _get_cached_file_id,
    _store_cached_file_id,
    build_card_message,
    build_plain_card_message,
)


def _card(question="What?", answer="Because.", card_id=7):
    return {"id": card_id, "question": question, "answer": answer}


# --- render_markdown_v2 ---

def test_inline_dollar_math_becomes_unicode_code_span():
    out = render_markdown_v2(r"Here $\alpha$ is the learning rate.")
    assert "`α`" in out


def test_display_math_becomes_pre_block():
    out = render_markdown_v2(r"$$\sum_{i=1}^{n} i = \frac{n(n+1)}{2}$$")
    assert "```" in out
    assert "∑" in out


def test_paren_delimiters_are_normalized_to_dollars():
    out = render_markdown_v2(r"Rate \(\alpha\) here.")
    assert "`α`" in out


def test_bracket_delimiters_are_normalized_to_display_math():
    out = render_markdown_v2(r"\[\sum_{i=1}^{n} i\]")
    assert "∑" in out


def test_code_fence_is_preserved_with_language():
    out = render_markdown_v2("```python\nprint('hi')\n```")
    assert out.startswith("```python")


def test_math_delimiters_inside_code_are_untouched():
    out = render_markdown_v2("```tex\n\\(x\\)\n```")
    assert "$x$" not in out


def test_currency_dollars_are_left_alone():
    out = render_markdown_v2("It costs $5 and I have $10.")
    assert "$5" in out
    assert "$10" in out


def test_markdown_emphasis_is_converted():
    out = render_markdown_v2("This is **important**.")
    assert "*important*" in out


def test_falls_back_to_escaped_text_on_conversion_error(monkeypatch):
    def boom(*args, **kwargs):
        raise ValueError("boom")

    monkeypatch.setattr(telegram_format.telegramify_markdown, "markdownify", boom)
    assert render_markdown_v2("hello_world") == "hello\\_world"


# --- spoiler_safe ---

def test_code_span_is_not_spoiler_safe():
    assert not spoiler_safe("uses `code` here")


def test_escaped_backtick_is_spoiler_safe():
    assert spoiler_safe(r"a literal \` tick")


def test_blockquote_is_not_spoiler_safe():
    assert not spoiler_safe("line one\n>a quote")


def test_plain_formatted_text_is_spoiler_safe():
    assert spoiler_safe("just *bold* and _italic_ text")


# --- needs_screenshot (the screenshot-pipeline gate) ---

def test_display_math_needs_screenshot():
    assert needs_screenshot(r"The identity: $$e^{i\pi} + 1 = 0$$")
    assert needs_screenshot("Result:\n\\[ x = 1 \\]")


def test_sums_integrals_fractions_need_screenshot():
    assert needs_screenshot(r"Compute $\sum_{i=1}^{n} i$ first.")
    assert needs_screenshot(r"$\int_0^1 x\,dx$")
    assert needs_screenshot(r"So $\frac{a}{b}$ holds.")


def test_latex_environment_needs_screenshot():
    assert needs_screenshot(r"\begin{pmatrix} a & b \\ c & d \end{pmatrix}")


def test_simple_inline_math_stays_text():
    assert not needs_screenshot(r"Note that $f(x) \in \mathbb{R}$ for all $x_0$.")
    assert not needs_screenshot(r"Here $\alpha$ is the learning rate.")


def test_in_does_not_match_int():
    assert not needs_screenshot(r"$a \in B$ and $\intercal$ notation")


def test_plain_text_and_code_stay_text():
    assert not needs_screenshot("Just a **regular** card.")
    assert not needs_screenshot("```python\nprint('hi')\n```")


def test_heavy_math_inside_code_block_stays_text():
    assert not needs_screenshot("```tex\n\\frac{a}{b} and $$x$$\n```")


# --- build_card_message ---

def test_plain_answer_keeps_spoiler_flow():
    text, keyboard = build_card_message(_card(answer="Just plain text."))
    assert "||Just plain text\\.||" in text
    buttons = [b for row in keyboard.inline_keyboard for b in row]
    assert [b.text for b in buttons] == ["View on Web"]


def test_math_answer_gets_show_answer_button():
    text, keyboard = build_card_message(_card(answer=r"It equals $\alpha^2$."))
    assert "||" not in text
    assert "Answer" not in text
    assert keyboard.inline_keyboard[0][0].callback_data == "ans:7"


def test_code_answer_gets_show_answer_button():
    text, keyboard = build_card_message(_card(answer="Use `dict.get(key)`."))
    assert "||" not in text
    assert keyboard.inline_keyboard[0][0].callback_data == "ans:7"


def test_reveal_shows_answer_without_spoiler_or_button():
    text, keyboard = build_card_message(_card(answer=r"It equals $\alpha^2$."), reveal=True)
    assert "α²" in text
    assert "||" not in text
    buttons = [b for row in keyboard.inline_keyboard for b in row]
    assert all(b.callback_data is None for b in buttons)


def test_plain_builder_matches_original_format():
    text, keyboard = build_plain_card_message(_card(question="a_b", answer="c*d"))
    assert text == "*Question:* a\\_b\n\n*Answer:* ||c\\*d||"
    buttons = [b for row in keyboard.inline_keyboard for b in row]
    assert [b.text for b in buttons] == ["View on Web"]


# --- Photo cache helpers ---

class _BrokenConn:
    """Connection stub whose queries always fail (e.g. cache table missing)."""

    def __init__(self):
        self.rolled_back = False

    def cursor(self, *args, **kwargs):
        raise RuntimeError("relation \"telegram_photo_cache\" does not exist")

    def rollback(self):
        self.rolled_back = True


def test_answer_cache_key_is_content_addressed():
    assert _answer_cache_key("same") == _answer_cache_key("same")
    assert _answer_cache_key("same") != _answer_cache_key("different")


def test_cache_lookup_degrades_gracefully_and_rolls_back():
    conn = _BrokenConn()
    assert _get_cached_file_id(conn, "some-key") is None
    assert conn.rolled_back


def test_cache_store_degrades_gracefully_and_rolls_back():
    conn = _BrokenConn()
    _store_cached_file_id(conn, "some-key", "file-id", 1)  # must not raise
    assert conn.rolled_back
