"""Prose path-extractor scorer.

When the agent emits prose-only diagnosis (no JSON tail), `score_run`
falls through to this scorer. It mines the diagnosis for relative
paths with known source extensions, bare basenames, and intersects
those with the ground-truth `fix.files` list to compute hits +
precision + recall.

FP guards:

- Stoplist of too-common basenames (`index.ts`, `main.c`, `utils.js`,
  ...) so a bare `index.ts` cite doesn't auto-match.
- Solve threshold is `recall ≥ 0.5 AND precision ≥ 0.25` — the
  shotgun-list case ("could be any of 7 files") gets recall=1.0 but
  fails the precision floor.

`any_hit` is exposed alongside `solved` so the orchestrator can route
ambiguous "named one right file but missed recall" rows into a
`needs_review` bucket instead of a hard ✗.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

_SOURCE_EXTS_RAW = (
    "c", "cc", "cpp", "h", "hpp",
    "ts", "tsx", "js", "jsx", "mjs", "cjs",
    "py", "go", "rs", "rb", "java",
    "glsl", "vert", "frag", "comp", "geom",
    "gd", "gdshader",
)
# Sort longest-first GLOBALLY. Regex alternation matches left-to-right,
# so a shorter extension that's a prefix of another one (e.g. `c`
# matching the start of `.cpp` or `.cjs`) wins and truncates the path.
# Sorting longest-first guarantees the regex tries `cpp`/`cjs`/`hpp`
# /`tsx`/`gdshader` before their shorter prefixes. R12c silently lost
# every such hit before this ordering.
_SOURCE_EXTS = tuple(sorted(_SOURCE_EXTS_RAW, key=len, reverse=True))
_EXT_GROUP = "|".join(_SOURCE_EXTS)

# Path with at least one '/' — matches `src/foo.ts`, `packages/x/y.cpp`.
_PATH_RE = re.compile(
    r"[`'\"]?([\w./-]+/[\w./-]+\.(?:%s))[`'\"]?" % _EXT_GROUP
)
# Bare basename: backticked or quoted only, no slashes, with a known
# source extension.
_BARE_BASENAME_RE = re.compile(
    r"[`'\"]([\w.-]+\.(?:%s))[`'\"]" % _EXT_GROUP
)

# Too-common basenames that shouldn't auto-hit when cited alone.
_STOPLIST_BASENAMES = frozenset({
    "index.ts", "index.js", "index.tsx",
    "main.c", "main.cpp", "main.cc", "main.py",
    "utils.js", "utils.ts", "util.js", "util.ts",
    "types.ts", "types.js",
    "helper.h", "helpers.h", "helper.cpp",
    "config.js", "config.ts",
    "constants.ts", "constants.js",
    "common.js", "common.ts", "common.h",
    "lib.rs",
})

_RECALL_THRESHOLD = 0.5
_PRECISION_THRESHOLD = 0.25


@dataclass
class ProseScore:
    file_hits: set[str] = field(default_factory=set)
    cited_paths: set[str] = field(default_factory=set)
    cited_basenames: set[str] = field(default_factory=set)
    precision: float = 0.0
    recall: float = 0.0
    any_hit: bool = False
    solved: bool = False


def score_prose(diagnosis_text: str, gt_files: list[str]) -> ProseScore:
    if not diagnosis_text or not gt_files:
        return ProseScore()

    cited_paths = {m for m in _PATH_RE.findall(diagnosis_text)}
    cited_basenames = {
        m for m in _BARE_BASENAME_RE.findall(diagnosis_text)
        if "/" not in m
    }
    # Path-derived basenames count too — citing `src/foo.ts` lets us
    # match a gt entry by basename even if the directory differs.
    path_basenames = {p.rsplit("/", 1)[-1] for p in cited_paths}

    gt_basenames = {f.rsplit("/", 1)[-1]: f for f in gt_files}
    file_hits: set[str] = set()
    for f in gt_files:
        if f in cited_paths:
            file_hits.add(f)
            continue
        base = f.rsplit("/", 1)[-1]
        if base in _STOPLIST_BASENAMES:
            continue
        if base in cited_basenames or base in path_basenames:
            file_hits.add(f)

    # Precision = hits / (distinct citations). Each path counts once;
    # basenames that aren't already implied by a cited path count as
    # additional citations. Stoplist common-name cites are noise so
    # they don't bloat the denominator.
    extra_basenames = {
        b for b in cited_basenames
        if b not in _STOPLIST_BASENAMES and b not in path_basenames
    }
    denom = max(len(cited_paths) + len(extra_basenames), 1)
    precision = len(file_hits) / denom
    recall = len(file_hits) / len(gt_files)
    any_hit = len(file_hits) > 0
    solved = (
        recall >= _RECALL_THRESHOLD and precision >= _PRECISION_THRESHOLD
    )

    return ProseScore(
        file_hits=file_hits,
        cited_paths=cited_paths,
        cited_basenames=cited_basenames | path_basenames,
        precision=precision,
        recall=recall,
        any_hit=any_hit,
        solved=solved,
    )
