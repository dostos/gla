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
    print_stream: TextIO = sys.stdout,
    err_stream: TextIO = sys.stderr,
) -> int:
    """Resolve user_path under root, read the file, write JSON, return rc."""
    try:
        target = resolve_relative(root, user_path)
    except LocalRootError as e:
        print(str(e), file=err_stream)
        return 2
    if not target.is_file():
        print(f"not a file: {user_path}", file=err_stream)
        return 2
    raw = target.read_bytes()
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
