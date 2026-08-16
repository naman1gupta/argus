"""Client-side PII masking: prefix-anchored secrets first, then checksummed
numerics (Luhn/Verhoeff), then plain patterns. Runs BEFORE truncation and
before any byte leaves the process. Names/addresses need NER — out of scope,
documented in the README with Presidio as the production path."""

import re

_PATTERNS: list[tuple[str, re.Pattern, object]] = []


def _luhn_ok(digits: str) -> bool:
    total, alt = 0, False
    for d in reversed(digits):
        n = int(d)
        if alt:
            n *= 2
            if n > 9:
                n -= 9
        total += n
        alt = not alt
    return total % 10 == 0


_VERHOEFF_D = [
    [0,1,2,3,4,5,6,7,8,9],[1,2,3,4,0,6,7,8,9,5],[2,3,4,0,1,7,8,9,5,6],[3,4,0,1,2,8,9,5,6,7],
    [4,0,1,2,3,9,5,6,7,8],[5,9,8,7,6,0,4,3,2,1],[6,5,9,8,7,1,0,4,3,2],[7,6,5,9,8,2,1,0,4,3],
    [8,7,6,5,9,3,2,1,0,4],[9,8,7,6,5,4,3,2,1,0],
]  # fmt: skip
_VERHOEFF_P = [
    [0,1,2,3,4,5,6,7,8,9],[1,5,7,6,2,8,3,0,9,4],[5,8,0,3,7,9,6,1,4,2],[8,9,1,6,0,4,3,5,2,7],
    [9,4,5,3,1,2,6,8,7,0],[4,2,8,6,5,7,3,9,0,1],[2,7,9,3,8,0,6,4,1,5],[7,0,4,6,9,1,3,2,5,8],
]  # fmt: skip


def _verhoeff_ok(digits: str) -> bool:
    c = 0
    for i, d in enumerate(reversed(digits)):
        c = _VERHOEFF_D[c][_VERHOEFF_P[i % 8][int(d)]]
    return c == 0


def _card_valid(m: re.Match) -> bool:
    digits = re.sub(r"[ -]", "", m.group())
    return 13 <= len(digits) <= 19 and _luhn_ok(digits)


def _aadhaar_valid(m: re.Match) -> bool:
    digits = re.sub(r"[\s-]", "", m.group())
    return len(digits) == 12 and digits[0] >= "2" and _verhoeff_ok(digits)


def _ssn_valid(m: re.Match) -> bool:
    area, group, serial = m.group().split("-")
    return not (area in ("000", "666") or area.startswith("9") or group == "00" or serial == "0000")


def _add(name: str, pattern: str, validator=None):
    _PATTERNS.append((name, re.compile(pattern), validator))


_add("API_KEY", r"\b(?:sk-ant-(?:api|admin)\d{2}-[A-Za-z0-9_-]{20,}"
     r"|sk-[A-Za-z0-9_-]{20,}"
     r"|(?:A3T[A-Z0-9]|AKIA|ASIA|ABIA|ACCA)[A-Z2-7]{16}"
     r"|gh[pousr]_[0-9a-zA-Z]{36}"
     r"|(?:sk|rk)_(?:test|live|prod)_[a-zA-Z0-9]{10,99}"
     r"|xoxb-[0-9]{10,13}-[0-9]{10,13}[a-zA-Z0-9-]*)")  # fmt: skip
_add("JWT", r"\bey[A-Za-z0-9_-]{17,}\.ey[A-Za-z0-9_-]{17,}\.[A-Za-z0-9_-]{10,}={0,2}")
_add("EMAIL", r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_add("CREDIT_CARD", r"\b(?:\d[ -]?){13,19}\b", _card_valid)
_add("AADHAAR", r"\b[2-9]\d{3}[\s-]?\d{4}[\s-]?\d{4}\b", _aadhaar_valid)
_add("US_SSN", r"\b\d{3}-\d{2}-\d{4}\b", _ssn_valid)
_add("PHONE_IN", r"(?<!\d)(?:\+91[\-\s]?)?[6-9]\d{9}(?!\d)")
_add("IPV4", r"\b(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\b")


def mask(text: str) -> tuple[str, list[str]]:
    """Returns (masked_text, sorted list of entity types found)."""
    if not text:
        return text, []
    found: set[str] = set()
    for name, pattern, validator in _PATTERNS:
        def _repl(m, name=name, validator=validator):
            if validator and not validator(m):
                return m.group()
            found.add(name)
            return f"<{name}>"
        text = pattern.sub(_repl, text)
    return text, sorted(found)
