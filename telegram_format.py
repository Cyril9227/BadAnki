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

# Math that needs 2D layout turns to mush as Unicode text; such cards are
# sent as a rendered screenshot instead. Simple inline math (greek letters,
# subscripts, \in, f(x), ...) stays on the fast text path. The trailing
# lookahead keeps \int from matching longer commands like \intercal while
# still matching \sum_{i=1} (command names are letters only, so `_` ends one).
_DISPLAY_MATH = re.compile(r"\$\$.+?\$\$|\\\[.+?\\\]", re.DOTALL)
_HEAVY_LATEX = re.compile(
    r"\\(?:frac|dfrac|tfrac|cfrac|binom|sum|prod|coprod|int|iint|iiint|oint"
    r"|sqrt|lim|liminf|limsup|begin|over(?:brace|line|set)|under(?:brace|line|set)|stackrel)"
    r"(?![a-zA-Z])"
)


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


# Mirrors the web app's cloze pattern (layout.html: CLOZE_PATTERN). Detection
# is content-based, like the web's isClozeText — the card_type column is not
# guaranteed to exist.
_CLOZE = re.compile(r"\{\{c\d+::([^}]+)\}\}")


def is_cloze(text: str) -> bool:
    return bool(_CLOZE.search(text))


def cloze_plain_markdown_v2(text: str, reveal: bool = False) -> str:
    """Escape-everything cloze rendering: blanks become ||spoilers|| (or plain
    text when reveal=True), everything else is escaped literally. Always
    parseable, never shows a hidden answer."""
    parts = []
    last = 0
    for match in _CLOZE.finditer(text):
        parts.append(escape_markdown(text[last:match.start()], version=2))
        blank = escape_markdown(match.group(1), version=2)
        parts.append(blank if reveal else f"||{blank}||")
        last = match.end()
    parts.append(escape_markdown(text[last:], version=2))
    return "".join(parts)


def render_cloze_markdown_v2(text: str, reveal: bool = False) -> str:
    """Converts a cloze question to MarkdownV2 with each {{cN::...}} blank as
    an in-place ||spoiler|| — tapping the blank reveals it, which is the cloze
    experience. The failure fallback is the plain cloze renderer (not raw
    escaped text, which would print the {{...}} markup and leak the answers).
    """
    def replace(match):
        return match.group(1) if reveal else f"||{match.group(1)}||"

    try:
        return telegramify_markdown.markdownify(
            _normalize_math_delimiters(_CLOZE.sub(replace, text)), latex_escape=True
        ).strip()
    except Exception:
        logger.warning("cloze markdownify failed; falling back to escaped text.", exc_info=True)
        return cloze_plain_markdown_v2(text, reveal)


def spoiler_safe(markdown_v2: str) -> bool:
    """Whether converted MarkdownV2 text may be wrapped in a ||spoiler||.

    Telegram does not allow code/pre entities (which math and code snippets
    render as) or blockquotes inside a spoiler entity.
    """
    return not (_CODE_ENTITY.search(markdown_v2) or _BLOCKQUOTE_LINE.search(markdown_v2))


def needs_screenshot(text: str) -> bool:
    """Whether card content is too math-heavy to stay readable as Unicode
    text, i.e. it contains display math, a LaTeX environment, or constructs
    like sums/integrals/fractions. Content inside code blocks doesn't count —
    it renders fine as a code block."""
    parts = _CODE_SEGMENT.split(text)
    outside_code = "".join(parts[i] for i in range(0, len(parts), 2))
    return bool(_DISPLAY_MATH.search(outside_code) or _HEAVY_LATEX.search(outside_code))
