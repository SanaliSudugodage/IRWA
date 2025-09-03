# src/security/sanitize.py
from __future__ import annotations

from typing import Iterable, Optional

from bleach.sanitizer import Cleaner

# Bleach >= 6: no 'styles' kwarg on clean(); use Cleaner.
_cleaner = Cleaner(
    tags=[],            # disallow all HTML tags
    attributes={},      # disallow all attributes
    protocols=["http", "https", "mailto"],
    strip=True,         # strip disallowed tags rather than escape
)

#Takes any string (or None) and returns a plain, safe version—no HTML, scripts, or attributes
def sanitize_text(text: Optional[str]) -> str:
    """
    Return a plain, safe string. Accepts None.
    """
    if text is None:
        return ""
    return _cleaner.clean(str(text))

def sanitize_list_str(items: Optional[Iterable[str]]) -> list[str]:
    """
    Sanitize a list of strings; None -> []
    """
    if not items:
        return []
    out: list[str] = []
    for it in items:
        s = sanitize_text(it)
        if s:
            out.append(s)
    return out
