"""Gave-up detector — veto for the score orchestrator.

R12 audit found two scenarios where the agent bailed out with
boilerplate ("no upstream snapshot accessible", "cannot investigate
without source") yet the legacy keyword scorer marked them ✓ on
lexical accident. The orchestrator should veto any positive verdict
when this detector returns True for the diagnosis tail.

Patterns are intentionally narrow and inspect only the last 600
characters of the text so an agent that briefly considered giving up
before solving doesn't get false-flagged.
"""
from __future__ import annotations

import re
from typing import Optional


_TAIL_CHARS = 600

_GAVE_UP_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"no upstream snapshot accessible",
        r"cannot investigate without (?:the )?source",
        r"upstream snapshot is not (?:accessible|available)",
        r"unable to (?:read|access) (?:the )?upstream (?:repo|source)",
        r"no access to the (?:framework|source) code",
        r"\bI (?:cannot|can'?t) (?:provide|give) a (?:specific|concrete) "
        r"(?:diagnosis|fix|answer)\b",
        r"\bwithout access to the (?:codebase|source|repo)\b[^.]*\bcannot\b",
        r"\bthis is (?:a )?(?:speculative|guess)\b",
    ]
]


def is_gave_up(text: Optional[str]) -> bool:
    """True when the diagnosis tail looks like a bail-out.

    Inspects the last `_TAIL_CHARS` characters so an agent that
    considered giving up earlier but then found the answer isn't
    false-flagged.
    """
    if not text:
        return False
    tail = text[-_TAIL_CHARS:]
    return any(pat.search(tail) for pat in _GAVE_UP_PATTERNS)
