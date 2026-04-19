"""Registered diagnostic checks for ``gpa report`` / ``gpa check``.

Each check is a subclass of :class:`Check` that inspects frame data exposed
through a :class:`~gpa.cli.rest_client.RestClient` and returns zero or more
findings.  Checks are additive: more subclasses can be registered later
without touching the report command.

Keeping the registry as a simple list in deterministic order keeps the
report output reproducible — important for both eyeball diffs and token
budgeting.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Type


# --------------------------------------------------------------------------- #
# Data types
# --------------------------------------------------------------------------- #


@dataclass
class Finding:
    """A single issue produced by a check.

    ``summary`` is the one-liner shown in the report. ``detail`` is a dict
    of machine-readable fields surfaced via ``--json`` and the drill-down
    ``gpa check <name>`` command.
    """

    summary: str
    detail: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CheckResult:
    """Outcome of running one check on a frame."""

    name: str
    status: str  # "ok" | "warn" | "error"
    findings: List[Finding] = field(default_factory=list)
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "findings": [
                {"summary": f.summary, **f.detail} for f in self.findings
            ],
            **({"error": self.error} if self.error else {}),
        }


# --------------------------------------------------------------------------- #
# Base check protocol
# --------------------------------------------------------------------------- #


class Check:
    """Abstract base class for all diagnostic checks.

    Subclasses override :attr:`name` and :meth:`run`.  ``run`` returns a
    :class:`CheckResult`; raising is also fine — the report command will
    turn it into an ``error`` status.
    """

    name: str = "<unnamed>"

    def run(self, client, *, frame_id: int, dc_id: Optional[int] = None) -> CheckResult:
        raise NotImplementedError


# --------------------------------------------------------------------------- #
# Registry
# --------------------------------------------------------------------------- #


_REGISTRY: List[Type[Check]] = []


def register(cls: Type[Check]) -> Type[Check]:
    """Decorator-style registration.

    Also usable as a plain function.  Order of registration is preserved
    and used as the report output order.
    """
    _REGISTRY.append(cls)
    return cls


def all_checks() -> List[Check]:
    """Return fresh instances of every registered check, in order."""
    return [cls() for cls in _REGISTRY]


def get_check(name: str) -> Optional[Check]:
    """Return a fresh instance of the named check, or ``None``."""
    for cls in _REGISTRY:
        if cls.name == name:
            return cls()
    return None


def known_names() -> List[str]:
    return [cls.name for cls in _REGISTRY]


# --------------------------------------------------------------------------- #
# Auto-register builtin checks
# --------------------------------------------------------------------------- #


def _register_builtins() -> None:
    # Import-time side effect: each module registers itself via @register.
    from . import empty_capture  # noqa: F401
    from . import feedback_loops  # noqa: F401
    from . import nan_uniforms  # noqa: F401
    from . import missing_clear  # noqa: F401


_register_builtins()
