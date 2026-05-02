"""``gpa source read|grep`` — harness-local source access.

Operates inside ``$GPA_SOURCE_ROOT``. All paths are validated by
``gpa.cli.local_roots`` before any filesystem access.
"""
from __future__ import annotations

import argparse
import sys
from typing import TextIO

from gpa.cli.local_roots import (
    LocalRoot,
    LocalRootError,
    grep_root_json,
    read_file_json,
)


_DEFAULT_MAX_BYTES = 200_000
_DEFAULT_MAX_MATCHES = 50
_HARD_MAX_MATCHES = 500
_ENV_NAME = "GPA_SOURCE_ROOT"


def add_subparser(subparsers) -> None:
    p = subparsers.add_parser(
        "source",
        help="Harness-local source access (under $GPA_SOURCE_ROOT)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = p.add_subparsers(dest="source_cmd", required=True)

    p_read = sub.add_parser("read", help="Read a source file as JSON")
    p_read.add_argument("path", help="Path relative to $GPA_SOURCE_ROOT")
    p_read.add_argument(
        "--max-bytes", type=int, default=_DEFAULT_MAX_BYTES,
        help=f"Truncation cap (default {_DEFAULT_MAX_BYTES})",
    )

    p_grep = sub.add_parser("grep", help="Regex search across the source root")
    p_grep.add_argument("pattern", help="Python regex")
    p_grep.add_argument("--subdir", default="", help="Restrict to a subdir")
    p_grep.add_argument("--glob", default="", help="Filename glob, e.g. '*.c'")
    p_grep.add_argument(
        "--max-matches", type=int, default=_DEFAULT_MAX_MATCHES,
        help=f"Cap (default {_DEFAULT_MAX_MATCHES}, hard cap {_HARD_MAX_MATCHES})",
    )


def run_read(
    *, path: str, max_bytes: int,
    print_stream: TextIO = sys.stdout,
    err_stream: TextIO = sys.stderr,
) -> int:
    try:
        root = LocalRoot.from_env(_ENV_NAME)
    except LocalRootError as e:
        print(str(e), file=err_stream)
        return 2
    return read_file_json(
        root=root, user_path=path, max_bytes=max_bytes,
        print_stream=print_stream, err_stream=err_stream,
    )


def run_grep(
    *, pattern: str, subdir: str, glob: str, max_matches: int,
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
        print_stream=print_stream, err_stream=err_stream,
    )


def run(args: argparse.Namespace) -> int:
    sub = args.source_cmd
    if sub == "read":
        return run_read(path=args.path, max_bytes=args.max_bytes)
    if sub == "grep":
        return run_grep(
            pattern=args.pattern, subdir=args.subdir, glob=args.glob,
            max_matches=args.max_matches,
        )
    raise AssertionError(sub)
