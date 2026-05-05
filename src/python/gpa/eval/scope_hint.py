"""Compute a "fix scope hint" string from a list of ground-truth files.

The hint tells the agent the *size* and *area* of the canonical fix
without revealing which specific files were touched. Designed to
calibrate the agent's search (e.g. "look for buffer-format changes
across the renderer, not just the multiplier path") without leaking
the answer.

R12c forensic finding: agents that solved scenarios used ~half the
tokens of failed ones. Failures were dominated by reasoning-shallow
("stopped at first plausible mechanism") and file-mismatch
("diagnosed correctly but proposed fix in a different file").
The scope hint addresses both:

- Scope size signals "the fix is a 13-file refactor, not a 1-line
  change" so the agent knows to look for a system-level cause
- Scope area ("under servers/rendering/renderer_rd/") prunes the
  search space so the agent can spend its tokens on the right
  subsystem
"""
from __future__ import annotations

from collections import Counter
from typing import Sequence


def compute_scope_hint(files: Sequence[str]) -> str:
    """Return a short, informative scope hint string.

    Examples:
        >>> compute_scope_hint([])
        'no fix files recorded'
        >>> compute_scope_hint(["src/render/Renderer.ts"])
        '1 file in src/render/'
        >>> compute_scope_hint([
        ...     "servers/rendering/renderer_rd/forward_clustered/render_forward_clustered.cpp",
        ...     "servers/rendering/renderer_rd/forward_mobile/render_forward_mobile.cpp",
        ...     "servers/rendering/renderer_rd/storage_rd/render_scene_buffers_rd.cpp",
        ... ])
        '3 files under servers/rendering/renderer_rd/ (3 sub-directories: forward_clustered/, forward_mobile/, storage_rd/)'

    The hint is deliberately textual (not structured) so it can be
    embedded inline in a prompt without parsing.
    """
    if not files:
        return "no fix files recorded"

    files = [f for f in files if f]
    n = len(files)
    if n == 0:
        return "no fix files recorded"

    if n == 1:
        path = files[0]
        if "/" in path:
            return f"1 file in {path.rsplit('/', 1)[0]}/"
        return f"1 file ({path})"

    # Find the deepest directory prefix common to all files. We split
    # on "/" and take the longest common parts. The prefix excludes
    # the basename — it's a directory path.
    parts_lists = [f.split("/") for f in files]
    min_depth = min(len(pl) - 1 for pl in parts_lists)  # -1 to exclude basename
    common_depth = 0
    for i in range(min_depth):
        first = parts_lists[0][i]
        if all(pl[i] == first for pl in parts_lists):
            common_depth = i + 1
        else:
            break

    if common_depth == 0:
        # No shared prefix — fall back to top-level distribution.
        top_dirs = Counter(
            (pl[0] if len(pl) > 1 else "(root)") for pl in parts_lists
        )
        # Show top 3 + count of others.
        ordered = top_dirs.most_common()
        parts = [f"{d}/ ({c})" for d, c in ordered[:3]]
        if len(ordered) > 3:
            parts.append(f"+{len(ordered) - 3} others")
        return f"{n} files across top-level: {', '.join(parts)}"

    common_prefix = "/".join(parts_lists[0][:common_depth])

    # Within that common prefix, what's the distribution one level
    # deeper? This is the "where in the subsystem" signal.
    sub_dirs = Counter()
    for pl in parts_lists:
        if len(pl) > common_depth + 1:
            # there's at least one sub-dir between the common prefix
            # and the basename
            sub_dirs[pl[common_depth]] += 1
        else:
            sub_dirs["(direct)"] += 1

    if len(sub_dirs) == 1:
        only = next(iter(sub_dirs))
        if only == "(direct)":
            return f"{n} files in {common_prefix}/"
        return f"{n} files under {common_prefix}/{only}/"

    ordered = sub_dirs.most_common()
    if len(ordered) <= 3:
        parts = [
            f"{d}/" if d != "(direct)" else "(direct)"
            for d, _ in ordered
        ]
        return (
            f"{n} files under {common_prefix}/ "
            f"({len(ordered)} sub-directories: {', '.join(parts)})"
        )
    return (
        f"{n} files under {common_prefix}/ "
        f"({len(ordered)} sub-directories)"
    )


__all__ = ["compute_scope_hint"]
