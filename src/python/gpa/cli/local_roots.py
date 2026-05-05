"""Env-rooted path resolution shared by ``gpa source`` and ``gpa upstream``.

Both commands operate inside a per-scenario root directory communicated
via an env var (``GPA_SOURCE_ROOT``, ``GPA_UPSTREAM_ROOT``). All path
inputs are validated against that root before any filesystem access:

- absolute paths must resolve inside the root
- relative paths are resolved against the root
- ``..`` traversal that escapes the root is rejected
"""
from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, TextIO


class LocalRootError(Exception):
    """Bad env var, missing root, or rejected path."""


@dataclass(frozen=True)
class LocalRoot:
    env_name: str
    path: Path

    @classmethod
    def from_env(cls, env_name: str) -> "LocalRoot":
        raw = os.environ.get(env_name)
        if not raw:
            raise LocalRootError(f"{env_name} is not set")
        p = Path(raw).expanduser()
        if not p.exists():
            raise LocalRootError(f"{env_name}={raw!r} does not exist")
        if not p.is_dir():
            raise LocalRootError(f"{env_name}={raw!r} is not a directory")
        return cls(env_name=env_name, path=p)


def resolve_relative(root: LocalRoot, user_path: str) -> Path:
    """Resolve ``user_path`` against ``root``; reject anything escaping."""
    if not user_path:
        raise LocalRootError("path is empty")
    p = Path(user_path).expanduser()
    if p.is_absolute():
        candidate = p
    else:
        candidate = root.path / p
    resolved = candidate.resolve()
    root_resolved = root.path.resolve()
    try:
        resolved.relative_to(root_resolved)
    except ValueError:
        if p.is_absolute():
            raise LocalRootError(
                f"absolute path {user_path!r} is outside {root.env_name}"
            )
        raise LocalRootError(f"path {user_path!r} escapes root {root_resolved}")
    return resolved


def read_file_json(
    *,
    root: LocalRoot,
    user_path: str,
    max_bytes: int,
    line_start: int = 0,
    line_end: int = 0,
    print_stream: TextIO = sys.stdout,
    err_stream: TextIO = sys.stderr,
) -> int:
    """Resolve user_path under root, read the file, write JSON, return rc.

    When ``line_start > 0``, return only lines in ``[line_start, line_end]``
    (1-indexed, inclusive). Pairs with ``outline``: agent reads the
    outline, picks a function's line range, then reads only that hunk.
    Avoids pulling 300 KB of file content to find one 30-line function.
    """
    try:
        target = resolve_relative(root, user_path)
    except LocalRootError as e:
        print(str(e), file=err_stream)
        return 2
    if not target.is_file():
        print(f"not a file: {user_path}", file=err_stream)
        return 2
    raw = target.read_bytes()

    # Optional line-range slicing. If line_start is 0 (or negative),
    # behave as the legacy whole-file read.
    if line_start > 0:
        text_full = raw.decode("utf-8", errors="replace")
        lines = text_full.splitlines(keepends=True)
        end = line_end if line_end > 0 else len(lines)
        # Clamp to valid range (1-indexed)
        sliced = lines[max(0, line_start - 1):min(len(lines), end)]
        text = "".join(sliced)
        # Honour max_bytes on the sliced output too
        encoded = text.encode("utf-8")
        truncated = len(encoded) > max_bytes
        text = encoded[:max_bytes].decode("utf-8", errors="replace")
        obj = {
            "path": user_path,
            "bytes": len(raw),
            "line_start": line_start,
            "line_end": min(len(lines), end),
            "total_lines": len(lines),
            "truncated": truncated,
            "text": text,
        }
    else:
        truncated = len(raw) > max_bytes
        payload = raw[:max_bytes]
        text = payload.decode("utf-8", errors="replace")
        obj = {
            "path": user_path,
            "bytes": len(raw),
            "truncated": truncated,
            "text": text,
        }
    print(json.dumps(obj, ensure_ascii=False), file=print_stream)
    return 0


def grep_root_json(
    *,
    root: LocalRoot,
    pattern: str,
    subdir: str,
    glob: str,
    max_matches: int,
    hard_max: int,
    context: int = 0,
    print_stream: TextIO = sys.stdout,
    err_stream: TextIO = sys.stderr,
) -> int:
    """Regex-search files under root (optionally filtered by subdir/glob).

    Writes JSON ``{matches:[{path,line,text[,context_before,context_after]}],
    truncated}`` and returns rc.

    `context` controls grep -C: when >0, each match carries
    ``context_before`` and ``context_after`` arrays (up to N lines each,
    excluding the matched line). When 0 (default) the older shape is
    preserved for back-compat with existing consumers.
    """
    try:
        base = resolve_relative(root, subdir) if subdir else root.path
    except LocalRootError as e:
        print(str(e), file=err_stream)
        return 2
    cap = min(max(1, max_matches), hard_max)
    ctx = max(0, int(context))
    try:
        regex = re.compile(pattern)
    except re.error as e:
        print(f"bad pattern: {e}", file=err_stream)
        return 2
    matches: list[dict] = []
    truncated = False
    iterator: Iterable[Path] = (
        base.rglob(glob) if glob else base.rglob("*")
    )
    for path in iterator:
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        lines = text.splitlines()
        for idx, line in enumerate(lines):
            if regex.search(line):
                rel = path.relative_to(root.path).as_posix()
                m: dict = {"path": rel, "line": idx + 1, "text": line[:500]}
                if ctx > 0:
                    m["context_before"] = [
                        ln[:500] for ln in lines[max(0, idx - ctx):idx]
                    ]
                    m["context_after"] = [
                        ln[:500] for ln in lines[idx + 1:idx + 1 + ctx]
                    ]
                matches.append(m)
                if len(matches) >= cap:
                    truncated = True
                    break
        if truncated:
            break
    obj = {"matches": matches, "truncated": truncated}
    print(json.dumps(obj, ensure_ascii=False), file=print_stream)
    return 0


# ---------------------------------------------------------------------------
# Symbol-aware definition finder. Regex-based (no LSP/ctags), but knows
# enough per-language definition shapes that one call replaces a typical
# grep+read chain ("where is `Painter` defined?" → one match instead of
# 30 noise hits).
# ---------------------------------------------------------------------------


def _defn_pattern(template: str, name: str) -> "re.Pattern":
    """Substitute `{NAME}` in `template` with `re.escape(name)`."""
    return re.compile(template.replace("{NAME}", re.escape(name)))


_LANG_DEFS = {
    "c": {
        "exts": (".c", ".h"),
        "patterns": [
            ("function", r"^[\w\s*<>:&]+\b{NAME}\s*\([^;]*\)\s*\{?\s*$"),
            ("typedef",  r"\btypedef\b[^;]*\b{NAME}\s*[;\(]"),
            ("struct",   r"\bstruct\s+{NAME}\b"),
        ],
    },
    "cpp": {
        "exts": (".cpp", ".cc", ".cxx", ".hpp", ".hh", ".h", ".inc"),
        "patterns": [
            ("function",  r"^[\w\s*<>:&,]+\b{NAME}\s*\([^;]*\)\s*\{?\s*$"),
            ("class",     r"\bclass\s+{NAME}\b"),
            ("struct",    r"\bstruct\s+{NAME}\b"),
            ("namespace", r"\bnamespace\s+{NAME}\b"),
        ],
    },
    "ts": {
        "exts": (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"),
        "patterns": [
            ("function", r"\bfunction\s+\*?{NAME}\b"),
            ("class",    r"\bclass\s+{NAME}\b"),
            ("const",    r"^\s*(?:export\s+)?(?:const|let|var)\s+{NAME}\b"),
            ("method",   r"^\s+(?:public\s+|private\s+|protected\s+|static\s+)*"
                          r"{NAME}\s*\([^;]*\)\s*\{"),
        ],
    },
    "py": {
        "exts": (".py",),
        "patterns": [
            ("function", r"^\s*(?:async\s+)?def\s+{NAME}\s*\("),
            ("class",    r"^\s*class\s+{NAME}\b"),
        ],
    },
    "rs": {
        "exts": (".rs",),
        "patterns": [
            ("function", r"\bfn\s+{NAME}\b"),
            ("struct",   r"\bstruct\s+{NAME}\b"),
            ("trait",    r"\btrait\s+{NAME}\b"),
            ("enum",     r"\benum\s+{NAME}\b"),
        ],
    },
    "go": {
        "exts": (".go",),
        "patterns": [
            ("function", r"\bfunc\s+(?:\([^)]*\)\s*)?{NAME}\b"),
            ("type",     r"\btype\s+{NAME}\b"),
        ],
    },
    "gdscript": {
        "exts": (".gd",),
        "patterns": [
            ("function", r"^\s*(?:static\s+)?func\s+{NAME}\s*\("),
            ("class",    r"^class_name\s+{NAME}\b"),
            ("signal",   r"^signal\s+{NAME}\b"),
        ],
    },
    "glsl": {
        "exts": (".glsl", ".vert", ".frag", ".comp", ".geom", ".gdshader"),
        "patterns": [
            ("function", r"^\s*\w+\s+{NAME}\s*\("),
        ],
    },
}


def _langs_for_file(path: Path) -> list[str]:
    """Return the lang keys whose `exts` claim this file."""
    suffix = path.suffix.lower()
    return [lang for lang, spec in _LANG_DEFS.items() if suffix in spec["exts"]]


def find_symbol_json(
    *,
    root: LocalRoot,
    name: str,
    subdir: str,
    lang: str,
    max_matches: int,
    print_stream: TextIO = sys.stdout,
    err_stream: TextIO = sys.stderr,
) -> int:
    """Scan files under root for definition-shaped lines naming `name`.

    Returns ``{matches: [{path, line, kind, signature, lang}], truncated}``
    in JSON.
    """
    try:
        base = resolve_relative(root, subdir) if subdir else root.path
    except LocalRootError as e:
        print(str(e), file=err_stream)
        return 2
    if not name:
        print("symbol name is empty", file=err_stream)
        return 2

    if lang and lang not in _LANG_DEFS:
        print(
            f"unknown lang {lang!r}; known: {sorted(_LANG_DEFS)}",
            file=err_stream,
        )
        return 2

    # Compile per-lang patterns once.
    compiled: dict[str, list[tuple[str, "re.Pattern"]]] = {
        lng: [(kind, _defn_pattern(tpl, name)) for kind, tpl in spec["patterns"]]
        for lng, spec in _LANG_DEFS.items()
    }

    matches: list[dict] = []
    truncated = False
    cap = max(1, int(max_matches))
    for path in base.rglob("*"):
        if truncated:
            break
        if not path.is_file():
            continue
        if lang:
            # Restrict to files whose extension belongs to that lang.
            if path.suffix.lower() not in _LANG_DEFS[lang]["exts"]:
                continue
            candidate_langs = [lang]
        else:
            candidate_langs = _langs_for_file(path)
        if not candidate_langs:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        rel = path.relative_to(root.path).as_posix()
        for idx, line in enumerate(text.splitlines()):
            for lng in candidate_langs:
                for kind, pat in compiled[lng]:
                    if pat.search(line):
                        matches.append({
                            "path": rel, "line": idx + 1, "kind": kind,
                            "signature": line.strip()[:300],
                            "lang": lng,
                        })
                        break
                else:
                    continue
                break
            if len(matches) >= cap:
                truncated = True
                break
    print(
        json.dumps(
            {"matches": matches, "truncated": truncated},
            ensure_ascii=False,
        ),
        file=print_stream,
    )
    return 0


# ---------------------------------------------------------------------------
# Outline: enumerate ALL definitions in a single file. Token-efficient
# triage path — agents typically `read PATH` (300-400 KB on godot/cesium),
# burning 5-10k tokens to find one function. `outline PATH` returns just
# the structural skeleton (~5 KB on the same files) so the agent can
# decide which line range actually warrants a full read.
#
# Driven by R12c-R14 forensics: failed scenarios spend ~2x tokens of
# solved ones, dominated by full-file reads on large framework sources.
# ---------------------------------------------------------------------------


# Outline patterns capture the symbol name with a group. Most are
# adapted from `_LANG_DEFS` patterns above with `{NAME}` replaced by
# `(\w+)` so the outline can list every symbol of each kind.
_OUTLINE_PATTERNS: dict[str, list[tuple[str, str]]] = {
    "c": [
        ("function", r"^[\w\s*<>:&]+\b(\w+)\s*\([^;]*\)\s*\{?\s*$"),
        ("typedef",  r"\btypedef\b[^;]*\b(\w+)\s*[;\(]"),
        ("struct",   r"\bstruct\s+(\w+)\b"),
    ],
    "cpp": [
        ("function",  r"^[\w\s*<>:&,]+\b(\w+)\s*\([^;]*\)\s*\{?\s*$"),
        ("class",     r"\bclass\s+(\w+)\b"),
        ("struct",    r"\bstruct\s+(\w+)\b"),
        ("namespace", r"\bnamespace\s+(\w+)\b"),
    ],
    "ts": [
        ("function", r"\bfunction\s+\*?(\w+)\b"),
        ("class",    r"\bclass\s+(\w+)\b"),
        ("const",    r"^\s*(?:export\s+)?(?:const|let|var)\s+(\w+)\b"),
        ("interface", r"\binterface\s+(\w+)\b"),
        ("type",     r"^\s*(?:export\s+)?type\s+(\w+)\b"),
    ],
    "py": [
        ("function", r"^\s*(?:async\s+)?def\s+(\w+)\s*\("),
        ("class",    r"^\s*class\s+(\w+)\b"),
    ],
    "rs": [
        ("function", r"\bfn\s+(\w+)\b"),
        ("struct",   r"\bstruct\s+(\w+)\b"),
        ("trait",    r"\btrait\s+(\w+)\b"),
        ("enum",     r"\benum\s+(\w+)\b"),
        ("impl",     r"\bimpl(?:\s*<[^>]*>)?\s+(?:[\w:]+\s+for\s+)?(\w+)\b"),
    ],
    "go": [
        ("function", r"\bfunc\s+(?:\([^)]*\)\s*)?(\w+)\b"),
        ("type",     r"\btype\s+(\w+)\b"),
    ],
    "gdscript": [
        ("function", r"^\s*(?:static\s+)?func\s+(\w+)\s*\("),
        ("class",    r"^class_name\s+(\w+)\b"),
        ("signal",   r"^signal\s+(\w+)\b"),
    ],
    "glsl": [
        ("function", r"^\s*\w+\s+(\w+)\s*\("),
    ],
}


# Names that look like definitions to the regex but are actually
# control flow / type-decl keywords. Filter these out of outline
# results so the noise doesn't drown the real definitions.
_OUTLINE_NOISE_NAMES = frozenset({
    "if", "for", "while", "switch", "return", "else", "do",
    "case", "default", "goto", "break", "continue",
    "sizeof", "alignof", "typeof", "decltype",
    "new", "delete", "throw", "try", "catch",
    "static_assert", "static_cast", "dynamic_cast", "const_cast",
    "reinterpret_cast",
    # Common method-call sites that match the function regex
    "memcpy", "memset", "memmove", "printf", "fprintf",
    "ERR_FAIL_COND", "ERR_FAIL_NULL", "ERR_FAIL_INDEX",
    "ERR_FAIL_COND_V", "ERR_FAIL_NULL_V", "ERR_FAIL_INDEX_V",
    "ERR_PRINT", "WARN_PRINT", "DEV_ASSERT",
})


def _compile_outline(lang: str) -> list[tuple[str, "re.Pattern"]]:
    return [(kind, re.compile(tpl)) for kind, tpl in _OUTLINE_PATTERNS[lang]]


def outline_file_json(
    *,
    root: LocalRoot,
    user_path: str,
    max_definitions: int = 500,
    print_stream: TextIO = sys.stdout,
    err_stream: TextIO = sys.stderr,
) -> int:
    """Emit a structural outline of a single file.

    Returns ``{path, lang, total_lines, file_size_bytes, definitions, truncated}``
    in JSON. ``definitions`` is a list of ``{kind, name, line, signature}``.

    Use case: a 300-KB framework file (godot renderer, cesium engine)
    fits in ~5 KB of outline. The agent triages by outline, then reads
    a 50-line range around the function it cares about — not the whole
    file. R12c-R14 forensics: full-file reads dominated failed-scenario
    token budgets (5-10k tokens per read on these files).
    """
    try:
        target = resolve_relative(root, user_path)
    except LocalRootError as e:
        print(str(e), file=err_stream)
        return 2
    if not target.is_file():
        print(f"not a file: {user_path}", file=err_stream)
        return 2

    langs = _langs_for_file(target)
    if not langs:
        # Unknown language — emit a degenerate outline (line count only)
        # so the agent doesn't have to retry with `read`.
        try:
            text = target.read_text(encoding="utf-8", errors="replace")
            line_count = text.count("\n") + 1
        except OSError:
            line_count = 0
        try:
            size = target.stat().st_size
        except OSError:
            size = 0
        print(
            json.dumps({
                "path": user_path,
                "lang": "",
                "total_lines": line_count,
                "file_size_bytes": size,
                "definitions": [],
                "truncated": False,
                "note": "no outline patterns for this file extension",
            }, ensure_ascii=False),
            file=print_stream,
        )
        return 0

    # Pick the first matching language's patterns (most files have one)
    lang = langs[0]
    compiled = _compile_outline(lang)
    try:
        text = target.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        print(f"read failed: {e}", file=err_stream)
        return 2

    lines = text.splitlines()
    definitions: list[dict] = []
    truncated = False
    cap = max(1, int(max_definitions))
    for idx, line in enumerate(lines):
        for kind, pat in compiled:
            m = pat.search(line)
            if m:
                try:
                    name = m.group(1)
                except IndexError:
                    name = ""
                if name in _OUTLINE_NOISE_NAMES:
                    break  # control-flow keyword, not a real def
                definitions.append({
                    "kind": kind,
                    "name": name,
                    "line": idx + 1,
                    "signature": line.strip()[:120],
                })
                if len(definitions) >= cap:
                    truncated = True
                break
        if truncated:
            break

    try:
        size = target.stat().st_size
    except OSError:
        size = 0
    print(
        json.dumps({
            "path": user_path,
            "lang": lang,
            "total_lines": len(lines),
            "file_size_bytes": size,
            "definitions": definitions,
            "truncated": truncated,
        }, ensure_ascii=False),
        file=print_stream,
    )
    return 0
