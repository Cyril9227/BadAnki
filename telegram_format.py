# telegram_format.py
# Converts card content (Markdown + LaTeX) into Telegram MarkdownV2.

import logging
import re

import telegramify_markdown
from telegram.helpers import escape_markdown

logger = logging.getLogger(__name__)

# Fenced code blocks and inline code spans are split out first so that math
# normalization never rewrites code content. With re.split() the captured
# code segments land at odd indices.
_CODE_SEGMENT = re.compile(r"(```.*?```|`[^`\n]*`)", re.DOTALL)

# The web app's MathJax accepts \(...\) / \[...\] as well as $...$ / $$...$$.
# telegramify-markdown converts the dollar forms more reliably (the paren form
# is skipped for simple expressions like \(x_0\)), so normalize to dollars.
_PAREN_MATH = re.compile(r"\\\((.+?)\\\)", re.DOTALL)
_BRACKET_MATH = re.compile(r"\\\[(.+?)\\\]", re.DOTALL)

# Telegram rejects code/pre entities and blockquotes nested inside a
# ||spoiler||. A backtick preceded by a backslash is escaped literal text,
# not a code entity.
_CODE_ENTITY = re.compile(r"(?<!\\)`")
_BLOCKQUOTE_LINE = re.compile(r"^(\*\*)?>", re.MULTILINE)


def _normalize_math_delimiters(text: str) -> str:
    parts = _CODE_SEGMENT.split(text)
    for i in range(0, len(parts), 2):
        outside_code = _PAREN_MATH.sub(lambda m: f"${m.group(1)}$", parts[i])
        parts[i] = _BRACKET_MATH.sub(lambda m: f"$${m.group(1)}$$", outside_code)
    return "".join(parts)


def render_markdown_v2(text: str) -> str:
    r"""Converts card Markdown (with MathJax-style LaTeX) to Telegram MarkdownV2.

    Inline math becomes Unicode in a monospace span (e.g. $\alpha^2$ -> `α²`),
    display math becomes a pre block, and fenced code blocks become Telegram
    pre blocks with their language tag. Falls back to plain escaped text if
    conversion fails, so a card can always be sent.
    """
    try:
        return telegramify_markdown.markdownify(
            _normalize_math_delimiters(text), latex_escape=True
        ).strip()
    except Exception:
        logger.warning("markdownify failed; falling back to escaped plain text.", exc_info=True)
        return escape_markdown(text, version=2)


def spoiler_safe(markdown_v2: str) -> bool:
    """Whether converted MarkdownV2 text may be wrapped in a ||spoiler||.

    Telegram does not allow code/pre entities (which math and code snippets
    render as) or blockquotes inside a spoiler entity.
    """
    return not (_CODE_ENTITY.search(markdown_v2) or _BLOCKQUOTE_LINE.search(markdown_v2))
