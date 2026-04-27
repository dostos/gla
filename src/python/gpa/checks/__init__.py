"""GPA framework-config rule engine.

This package houses ``gpa check-config`` — a small library of rules that
cross-validate captured GL state against well-known framework
misconfiguration patterns. Lightweight by design: each rule is a Python
predicate, and the messages/severities/hints live in
``config_rules.yaml`` so they can be reviewed and iterated separately
from the predicate code.

Public entry points:

* :class:`Finding` — one rule fire on one frame.
* :class:`Rule` — ABC for a predicate; subclasses live in :mod:`rules`.
* :class:`RuleEngine` — load YAML metadata, register predicate classes,
  evaluate against a :class:`gpa.backends.base.FrameOverview`-shaped
  dict + draw-call list, return a list of :class:`Finding`.

Severity ordering: ``error`` > ``warn`` > ``info``.
"""

from gpa.checks.rules import (  # noqa: F401
    Finding,
    Rule,
    RuleEngine,
    SEVERITY_ORDER,
    default_engine,
)
