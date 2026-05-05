"""``gpa upstream read|list|grep`` — upstream repository access.

Operates inside ``$GPA_UPSTREAM_ROOT``. All paths are validated by
``gpa.cli.local_roots`` before any filesystem access.
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import TextIO

from gpa.cli.local_roots import (
    LocalRoot,
    LocalRootError,
    find_symbol_json,
    grep_root_json,
    outline_file_json,
    read_file_json,
    resolve_relative,
)


_DEFAULT_MAX_BYTES = 512_000  # raised from 200 K — godot files run 369–402 KB
_DEFAULT_MAX_MATCHES = 50
_HARD_MAX_MATCHES = 500
_ENV_NAME = "GPA_UPSTREAM_ROOT"


def add_subparser(subparsers) -> None:
    p = subparsers.add_parser(
        "upstream",
        help="Upstream repository access (under $GPA_UPSTREAM_ROOT)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = p.add_subparsers(dest="upstream_cmd", required=True)

    p_read = sub.add_parser("read", help="Read an upstream file as JSON")
    p_read.add_argument("path", help="Path relative to $GPA_UPSTREAM_ROOT")
    p_read.add_argument(
        "--max-bytes", type=int, default=_DEFAULT_MAX_BYTES,
        help=f"Truncation cap (default {_DEFAULT_MAX_BYTES})",
    )
    p_read.add_argument(
        "--lines", default="",
        help=(
            "Optional line-range, 1-indexed inclusive, e.g. '152..210'. "
            "Pairs with `outline` — outline gives you the function's "
            "starting line; read --lines pulls only that hunk."
        ),
    )

    p_list = sub.add_parser("list", help="List entries in an upstream directory")
    p_list.add_argument(
        "subdir", nargs="?", default="",
        help="Subdirectory relative to $GPA_UPSTREAM_ROOT (default: root)",
    )

    p_grep = sub.add_parser("grep", help="Regex search across the upstream root")
    p_grep.add_argument("pattern", help="Python regex")
    p_grep.add_argument("--subdir", default="", help="Restrict to a subdir")
    p_grep.add_argument("--glob", default="", help="Filename glob, e.g. '*.c'")
    p_grep.add_argument(
        "--max-matches", type=int, default=_DEFAULT_MAX_MATCHES,
        help=f"Cap (default {_DEFAULT_MAX_MATCHES}, hard cap {_HARD_MAX_MATCHES})",
    )
    p_grep.add_argument(
        "--context", "-C", type=int, default=0,
        help="Lines of context around each match (default 0).",
    )

    p_outline = sub.add_parser(
        "outline",
        help="Structural outline of a file (functions/classes/structs)",
        description=(
            "Lists every definition in PATH (kind + name + line + "
            "signature) without returning file contents. Use as a "
            "cheap triage before `read` — a 300-KB framework file "
            "outlines into ~5 KB. Then `read` only the range you need."
        ),
    )
    p_outline.add_argument("path", help="Path relative to $GPA_UPSTREAM_ROOT")
    p_outline.add_argument(
        "--max-definitions", type=int, default=500,
        help="Cap on definitions returned (default 500).",
    )

    p_find = sub.add_parser(
        "find-symbol",
        help="Locate a symbol's definition across the snapshot",
        description=(
            "Regex-based per-language definition finder. Knows function "
            "/ class / struct / typedef / etc. shapes for c, cpp, ts, "
            "py, rs, go, gdscript, glsl. One call beats grep+read chains."
        ),
    )
    p_find.add_argument("name", help="Symbol name (exact match)")
    p_find.add_argument("--subdir", default="", help="Restrict to a subdir")
    p_find.add_argument(
        "--lang", default="",
        help=(
            "Restrict to a single language (c, cpp, ts, py, rs, go, "
            "gdscript, glsl). Default: detect from each file extension."
        ),
    )
    p_find.add_argument(
        "--max-matches", type=int, default=_DEFAULT_MAX_MATCHES,
        help=f"Cap (default {_DEFAULT_MAX_MATCHES}).",
    )


def run_read(
    *, path: str, max_bytes: int, lines: str = "",
    print_stream: TextIO = sys.stdout,
    err_stream: TextIO = sys.stderr,
) -> int:
    try:
        root = LocalRoot.from_env(_ENV_NAME)
    except LocalRootError as e:
        print(str(e), file=err_stream)
        return 2
    line_start, line_end = 0, 0
    if lines:
        # Accept '152..210' or '152:210' or just '152' (single line)
        import re as _re
        m = _re.match(r"^(\d+)(?:[.:]+(\d+))?$", lines.strip())
        if not m:
            print(
                f"--lines expects 'START..END' or 'START:END' "
                f"or 'START' (got {lines!r})",
                file=err_stream,
            )
            return 2
        line_start = int(m.group(1))
        line_end = int(m.group(2)) if m.group(2) else line_start
    return read_file_json(
        root=root, user_path=path, max_bytes=max_bytes,
        line_start=line_start, line_end=line_end,
        print_stream=print_stream, err_stream=err_stream,
    )


def run_list(
    *, subdir: str,
    print_stream: TextIO = sys.stdout,
    err_stream: TextIO = sys.stderr,
) -> int:
    try:
        root = LocalRoot.from_env(_ENV_NAME)
        if subdir:
            base = resolve_relative(root, subdir)
            if not base.is_dir():
                print(f"not a directory: {subdir}", file=err_stream)
                return 2
        else:
            base = root.path
    except LocalRootError as e:
        print(str(e), file=err_stream)
        return 2
    entries = []
    for p in sorted(base.iterdir(), key=lambda x: x.name):
        entries.append({
            "name": p.name,
            "type": "dir" if p.is_dir() else "file",
        })
    obj = {"subdir": subdir, "entries": entries}
    print(json.dumps(obj, ensure_ascii=False), file=print_stream)
    return 0


def run_grep(
    *, pattern: str, subdir: str, glob: str, max_matches: int,
    context: int = 0,
    print_stream: TextIO = sys.stdout,
    err_stream: TextIO = sys.stderr,
) -> int:
    try:
        root = LocalRoot.from_env(_ENV_NAME)
    except LocalRootError as e:
        print(str(e), file=err_stream)
        return 2
    return grep_root_json(
        root=root, pattern=pattern, subdir=subdir, glob=glob,
        max_matches=max_matches, hard_max=_HARD_MAX_MATCHES,
        context=context,
        print_stream=print_stream, err_stream=err_stream,
    )


def run_outline(
    *, path: str, max_definitions: int,
    print_stream: TextIO = sys.stdout,
    err_stream: TextIO = sys.stderr,
) -> int:
    try:
        root = LocalRoot.from_env(_ENV_NAME)
    except LocalRootError as e:
        print(str(e), file=err_stream)
        return 2
    return outline_file_json(
        root=root, user_path=path, max_definitions=max_definitions,
        print_stream=print_stream, err_stream=err_stream,
    )


def run_find_symbol(
    *, name: str, subdir: str, lang: str, max_matches: int,
    print_stream: TextIO = sys.stdout,
    err_stream: TextIO = sys.stderr,
) -> int:
    try:
        root = LocalRoot.from_env(_ENV_NAME)
    except LocalRootError as e:
        print(str(e), file=err_stream)
        return 2
    return find_symbol_json(
        root=root, name=name, subdir=subdir, lang=lang,
        max_matches=max_matches,
        print_stream=print_stream, err_stream=err_stream,
    )


def run(args: argparse.Namespace) -> int:
    sub = args.upstream_cmd
    if sub == "read":
        return run_read(path=args.path, max_bytes=args.max_bytes,
                        lines=getattr(args, "lines", ""))
    if sub == "list":
        return run_list(subdir=args.subdir)
    if sub == "grep":
        return run_grep(
            pattern=args.pattern, subdir=args.subdir, glob=args.glob,
            max_matches=args.max_matches, context=args.context,
        )
    if sub == "outline":
        return run_outline(
            path=args.path, max_definitions=args.max_definitions,
        )
    if sub == "find-symbol":
        return run_find_symbol(
            name=args.name, subdir=args.subdir, lang=args.lang,
            max_matches=args.max_matches,
        )
    raise AssertionError(sub)
