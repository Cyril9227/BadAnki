import json
import re
from typing import Any

# Control character mappings for JSON parsing
_CONTROL_REPR = {
    0x08: r'\\b',   # backspace
    0x09: r'\\t',   # tab
    0x0a: r'\\n',   # newline
    0x0c: r'\\f',   # form-feed
    0x0d: r'\\r',   # carriage return
}

def _iter_strings(obj):
    """Recursively iterate over all strings in a nested data structure."""
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _iter_strings(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            yield from _iter_strings(v)

def _has_control_chars(obj) -> bool:
    """Check if any strings in the object contain control characters."""
    for s in _iter_strings(obj):
        if any(ord(ch) < 0x20 for ch in s):
            return True
    return False

def _strip_fences(s: str) -> str:
    """Remove markdown code fences from JSON response."""
    s = s.strip()
    if s.startswith("```json"):
        s = s[len("```json"):]
    if s.startswith("```"):
        s = s[3:]
    if s.endswith("```"):
        s = s[:-3]
    return s.strip()

def _restore_control_chars(parsed: Any) -> Any:
    """Walk parsed data and replace control chars with literal backslash-letter sequences."""
    if isinstance(parsed, str):
        # replace control chars with their backslash-letter form (e.g. \x0c -> '\f')
        out = []
        for ch in parsed:
            o = ord(ch)
            if o < 0x20:
                out.append(_CONTROL_REPR.get(o, '\\u%04x' % o))
            else:
                out.append(ch)
        return ''.join(out)
    elif isinstance(parsed, dict):
        return {k: _restore_control_chars(v) for k, v in parsed.items()}
    elif isinstance(parsed, list):
        return [_restore_control_chars(v) for v in parsed]
    else:
        return parsed

def robust_json_loads(raw: str) -> Any:
    """
    Robust JSON parsing for Ollama/LLM responses containing LaTeX.
    Strategy:
      1) try json.loads(raw)
      2) if that fails or control chars are detected -> pre-escape single backslashes before letters and parse
      3) if parsed contains control chars, restore them to literal backslash-letter sequences
    """
    s = _strip_fences(raw)

    # try plain parse first (fast path)
    try:
        parsed = json.loads(s)
        # if plain parsing succeeded and there are no control chars, return
        if not _has_control_chars(parsed):
            return parsed
        # else continue to fallback (we'll restore control chars below)
    except json.JSONDecodeError:
        parsed = None

    # Fallback: pre-escape single backslashes that precede letters.
    # This handles cases like "\frac", "\theta", "\times" (including those that start with f,t,...)
    # Pattern explanation: (?<!\\) ensure the backslash is not already escaped.
    s_escaped = re.sub(r'(?<!\\)\\(?=[A-Za-z])', r'\\\\', s)

    # Try parsing the escaped form
    parsed = json.loads(s_escaped)  # let exception propagate if this truly fails

    # If for any reason parsed strings still contain control chars (rare now), restore them
    if _has_control_chars(parsed):
        parsed = _restore_control_chars(parsed)

    return parsed

def normalize_latex_for_mathjax(text: str) -> str:
    """
    Collapse multiple backslashes to single backslash where it matters for LaTeX (before letters,
    and inside math delimiters). This avoids removing backslashes globally and avoids mutilating other escapes.
    """
    if not isinstance(text, str):
        return text

    # 1) collapse repeated backslashes before letters into a single backslash
    text = re.sub(r'\\{2,}([A-Za-z])', r'\\\1', text)

    # 2) inside math delimiters, collapse ANY sequence of backslashes to a single backslash
    def collapse_inner(m):
        inner = m.group(1)
        inner_fixed = re.sub(r'\\{2,}', r'\\', inner)
        return m.group(0).replace(inner, inner_fixed)

    # $ ... $
    text = re.sub(r'\$\$(.+?)\$\$', collapse_inner, text, flags=re.DOTALL)
    # $ ... $  (avoid matching $$)
    text = re.sub(r'(?<!\$)\\$$(?!\$)(.+?)(?<!\$)\\$$(?!\$)', collapse_inner, text, flags=re.DOTALL)
    # \( ... \
    text = re.sub(r'\\\((.+?)\\\\)', collapse_inner, text, flags=re.DOTALL)
    # \[ ... \]
    text = re.sub(r'\\\\[(.+?)\\\\].', collapse_inner, text, flags=re.DOTALL)

    return text

def normalize_cards(cards: list[dict]) -> list[dict]:
    """Apply LaTeX normalization to all string fields in cards."""
    out = []
    for card in cards:
        new = {}
        for k, v in card.items():
            if isinstance(v, str):
                new[k] = normalize_latex_for_mathjax(v)
            else:
                new[k] = v
        out.append(new)
    return out

def sanitize_tags(tags):
    """
    Sanitizes a list of tags by converting them to lowercase,
    stripping whitespace, and removing duplicates.
    Accepts a list of strings or a single comma-separated string.
    """
    if not tags:
        return []
    tag_list = []
    if isinstance(tags, list):
        tag_list = [str(t).strip().lower() for t in tags]
    elif isinstance(tags, str):
        tag_list = [t.strip().lower() for t in tags.split(',')]
    return sorted(list(set(tag_list)))
