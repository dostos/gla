"""Browser-based eval runner (Phase 1 MVP).

See ``docs/superpowers/specs/2026-04-20-gpa-browser-eval-design.md``.

Public API:

- :class:`BrowserRunner` — orchestrates a single scenario run.
- :class:`BrowserRunOptions` — options dataclass.
- :class:`BrowserRunResult` — result of one run.
- :func:`spawn_chromium` — default launcher (subprocess.Popen).
- :func:`autodetect_chromium` — finds a chromium binary on ``$PATH``.
- :exc:`ChromiumNotFoundError` — raised when no chromium binary is found.
"""

from gpa.browser.runner import (
    BrowserRunOptions,
    BrowserRunResult,
    BrowserRunner,
    ChromiumNotFoundError,
    autodetect_chromium,
    spawn_chromium,
)

__all__ = [
    "BrowserRunOptions",
    "BrowserRunResult",
    "BrowserRunner",
    "ChromiumNotFoundError",
    "autodetect_chromium",
    "spawn_chromium",
]
