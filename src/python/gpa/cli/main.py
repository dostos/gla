"""``gpa`` CLI entry point.

Usage:
    gpa start [--session DIR] [--daemon/--no-daemon] [--port PORT]
    gpa stop  [--session DIR]
    gpa env   [--session DIR]
    gpa run   [--session DIR] [--timeout SEC] [--port PORT] -- <cmd> [args...]

Exit codes:
    0 success
    1 runtime / engine failure
    2 no session found (stop/env)
    127 target command not found (run)
    other: propagated from the target's own exit code (run)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Optional, Sequence

from gpa.cli import __version__
from gpa.cli.commands import check as check_cmd
from gpa.cli.commands import check_config as check_config_cmd
from gpa.cli.commands import diff as diff_cmd
from gpa.cli.commands import diff_draws as diff_draws_cmd
from gpa.cli.commands import drawcalls as drawcalls_cmd
from gpa.cli.commands import dump as dump_cmd
from gpa.cli.commands import pixel as pixel_cmd
from gpa.cli.commands import scene as scene_cmd
from gpa.cli.commands import env as env_cmd
from gpa.cli.commands import explain_draw as explain_draw_cmd
from gpa.cli.commands import frames as frames_cmd
from gpa.cli.commands import report as report_cmd
from gpa.cli.commands import run as run_cmd
from gpa.cli.commands import run_browser as run_browser_cmd
from gpa.cli.commands import scene_explain as scene_explain_cmd
from gpa.cli.commands import scene_find as scene_find_cmd
from gpa.cli.commands import source as source_cmd
from gpa.cli.commands import upstream as upstream_cmd
from gpa.cli.commands import start as start_cmd
from gpa.cli.commands import stop as stop_cmd
from gpa.cli.commands import trace as trace_cmd


def _add_session_arg(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--session",
        dest="session",
        type=Path,
        default=None,
        help="Session directory (overrides $GPA_SESSION and the current-session link)",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gpa",
        description="OpenGPA — live graphics debugger CLI (Phase 1a).",
    )
    parser.add_argument("--version", action="version", version=f"gpa {__version__}")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_start = sub.add_parser(
        "start",
        help="Start a persistent engine session",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  gpa start                                       # 1) default port 18080\n"
            "  gpa start --port 0                              # 2) auto-pick free port\n"
            "  gpa start --no-daemon                           # 3) keep engine attached\n"
            "  eval \"$(gpa start)\"                             # 4) export env to shell\n"
        ),
    )
    _add_session_arg(p_start)
    p_start.add_argument(
        "--port",
        type=int,
        default=18080,
        help="REST API port (0 = auto-pick a free ephemeral port)",
    )
    p_start.add_argument(
        "--daemon",
        dest="daemon",
        action="store_true",
        default=True,
        help="Detach engine so it outlives this process (default)",
    )
    p_start.add_argument(
        "--no-daemon",
        dest="daemon",
        action="store_false",
        help="Keep engine in the current process group",
    )

    p_stop = sub.add_parser(
        "stop",
        help="Terminate the active session",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  gpa stop                                        # 1) stop active session\n"
            "  gpa stop --session /tmp/gpa-abc                 # 2) stop a specific session\n"
            "  GPA_SESSION=/tmp/gpa-abc gpa stop               # 3) via env\n"
        ),
    )
    _add_session_arg(p_stop)

    p_env = sub.add_parser(
        "env",
        help="Print env exports for the active session",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  gpa env                                         # 1) print exports\n"
            "  eval \"$(gpa env)\"                               # 2) load into shell\n"
            "  gpa env --session /tmp/gpa-abc                  # 3) specific session\n"
        ),
    )
    _add_session_arg(p_env)

    p_run = sub.add_parser(
        "run",
        help="Launch a target under an embedded engine + shim",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  gpa run -- ./my_gl_app                          # 1) simplest\n"
            "  gpa run --timeout 5 -- ./my_gl_app              # 2) auto-kill after 5s\n"
            "  gpa run --port 0 -- ./my_gl_app                 # 3) ephemeral port\n"
            "  gpa run -- bazel-bin/tests/eval/synthetic/state-leak/e1_state_leak/e1_state_leak  # 4) eval scenario\n"
        ),
    )
    _add_session_arg(p_run)
    p_run.add_argument("--port", type=int, default=18080, help="REST API port")
    p_run.add_argument(
        "--timeout",
        type=float,
        default=None,
        help="SIGTERM the target after N seconds (SIGKILL +3s)",
    )
    p_run.add_argument(
        "command",
        nargs=argparse.REMAINDER,
        help="Target command and arguments",
    )

    # ---- run-browser ------------------------------------------------------
    p_runb = sub.add_parser(
        "run-browser",
        help="Run a browser-mode eval scenario under Chromium + WebGL shim",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  gpa run-browser --scenario r21_threejs_envmap                # 1) simplest\n"
            "  gpa run-browser --scenario r21_threejs_envmap --timeout 60   # 2) longer wait\n"
            "  gpa run-browser --scenario my_scn --keep-open                # 3) leave chrome\n"
            "  gpa run-browser --scenario my_scn --chromium-path /usr/bin/chromium\n"
        ),
    )
    _add_session_arg(p_runb)
    p_runb.add_argument("--scenario", required=True,
                        help="Scenario name (directory under tests/eval-browser/)")
    p_runb.add_argument("--timeout", type=int, default=30,
                        help="Max seconds to wait for capture (default 30)")
    p_runb.add_argument("--chromium-path", default=None,
                        help="Path to chromium binary (default: autodetect)")
    p_runb.add_argument("--keep-open", action="store_true",
                        help="Do not terminate chromium on finish")
    p_runb.add_argument("--port", type=int, default=18080,
                        help="REST API port (only used if a new session is created)")

    # ---- report -----------------------------------------------------------
    p_report = sub.add_parser(
        "report",
        help="Run every diagnostic check on a captured frame",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  gpa report                                      # 1) latest frame\n"
            "  gpa report --frame 7                            # 2) specific frame\n"
            "  gpa report --json                               # 3) machine-readable\n"
            "  gpa report --only feedback-loops,nan-uniforms   # 4) subset\n"
            "  gpa report --skip empty-capture                 # 5) drop noisy checks\n"
        ),
    )
    _add_session_arg(p_report)
    p_report.add_argument("--frame", type=int, default=None,
                          help="Frame id (default: latest)")
    p_report.add_argument("--json", dest="json_output", action="store_true",
                          help="Emit JSON instead of plain text")
    p_report.add_argument("--only", type=str, default=None,
                          help="Comma-separated list of check names to run")
    p_report.add_argument("--skip", type=str, default=None,
                          help="Comma-separated list of check names to skip")

    # ---- check ------------------------------------------------------------
    p_check = sub.add_parser(
        "check",
        help="Drill-down into a single diagnostic",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  gpa check feedback-loops                        # 1) one check\n"
            "  gpa check nan-uniforms --frame 7                # 2) specific frame\n"
            "  gpa check feedback-loops --dc 12                # 3) one draw call\n"
            "  gpa check empty-capture --json                  # 4) JSON\n"
        ),
    )
    _add_session_arg(p_check)
    p_check.add_argument("name", help="Check name (e.g. feedback-loops)")
    p_check.add_argument("--frame", type=int, default=None)
    p_check.add_argument("--dc", type=int, default=None,
                         help="Filter to a single draw call id")
    p_check.add_argument("--json", dest="json_output", action="store_true")

    # ---- dump -------------------------------------------------------------
    # Per-draw subtargets (drawcall/shader/textures/attachments) were removed
    # in favour of the narrow ``gpa explain-draw`` and ``gpa check-config``
    # commands. The remaining three (frame / drawcalls / pixel) have no narrow
    # replacement yet.
    p_dump = sub.add_parser(
        "dump",
        help="Raw REST data access (frame | drawcalls | pixel)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  gpa dump frame                                  # 1) latest frame overview\n"
            "  gpa dump drawcalls --frame 7                    # 2) draw-call list\n"
            "  gpa dump pixel --x 100 --y 200                  # 3) pixel at (100,200)\n"
            "  gpa dump frame --format json                    # 4) JSON output\n"
            "  gpa dump drawcalls --format compact             # 5) one line per row\n"
        ),
    )
    _add_session_arg(p_dump)
    p_dump.add_argument("what", help="frame | drawcalls | pixel")
    p_dump.add_argument("--frame", type=int, default=None)
    p_dump.add_argument("--x", type=int, default=None)
    p_dump.add_argument("--y", type=int, default=None)
    p_dump.add_argument("--format", dest="fmt", default="plain",
                        choices=["plain", "json", "compact"])
    # Silently absorb trailing positional args (e.g. ``gpa dump drawcall 0``)
    # so removed subtargets reach the redirect handler instead of dying with
    # an argparse "unrecognized arguments" error (exit 2).
    #
    # NB: ``nargs="*"`` (NOT ``argparse.REMAINDER``). REMAINDER is greedy and
    # eats every subsequent token including option-like strings (e.g. it would
    # swallow ``--x 10`` from ``gpa dump pixel --x 10 --y 20``), leaving the
    # real flags as ``None`` and silently breaking ``dump pixel/frame/drawcalls``.
    # ``nargs="*"`` only absorbs trailing POSITIONALS, leaving flags for argparse.
    p_dump.add_argument("trailing", nargs="*", default=[],
                        help=argparse.SUPPRESS)

    # ---- frames -----------------------------------------------------------
    frames_cmd.add_subparser(sub)

    # ---- drawcalls --------------------------------------------------------
    drawcalls_cmd.add_subparser(sub)

    # ---- pixel ------------------------------------------------------------
    pixel_cmd.add_subparser(sub)

    # ---- scene ------------------------------------------------------------
    scene_cmd.add_subparser(sub)

    # ---- source -----------------------------------------------------------
    source_cmd.add_subparser(sub)

    # ---- upstream ---------------------------------------------------------
    upstream_cmd.add_subparser(sub)

    # ---- check-config -----------------------------------------------------
    check_config_cmd.add_subparser(sub)

    # ---- diff -------------------------------------------------------------
    diff_cmd.add_subparser(sub)

    # ---- bidirectional narrow scene↔GL queries ----------------------------
    explain_draw_cmd.add_subparser(sub)
    diff_draws_cmd.add_subparser(sub)
    scene_find_cmd.add_subparser(sub)
    scene_explain_cmd.add_subparser(sub)

    # ---- trace ------------------------------------------------------------
    p_trace = sub.add_parser(
        "trace",
        help=(
            "Reverse-lookup a captured value → app-level fields that hold it. "
            "Requires a value scanner (native DWARF symbols or WebGL Tier-3 "
            "SDK) to be active in the target."
        ),
    )
    _add_session_arg(p_trace)
    trace_sub = p_trace.add_subparsers(dest="trace_cmd", required=True)

    p_t_uniform = trace_sub.add_parser(
        "uniform",
        help="Trace a uniform by name (requires --dc)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  gpa trace uniform uZoom --dc 4                  # 1) simplest\n"
            "  gpa trace uniform uZoom --dc 4 --frame 7        # 2) specific frame\n"
            "  gpa trace uniform uZoom --dc 4 --json           # 3) JSON\n"
            "  gpa scene-find uniform-has-nan --json \\\n"
            "    | jq -r '.matches[].draw_call_ids[0]' \\\n"
            "    | xargs -I% gpa trace uniform uColor --dc %   # 4) pipeline\n"
        ),
    )
    p_t_uniform.add_argument("name", help="Uniform name (e.g. uZoom)")
    p_t_uniform.add_argument("--frame", type=int, default=None)
    p_t_uniform.add_argument("--dc", type=int, default=None)
    p_t_uniform.add_argument("--json", dest="json_output", action="store_true")

    p_t_value = trace_sub.add_parser(
        "value",
        help="Trace a literal value (number/string/bool) across the frame",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  gpa trace value 16.58                           # 1) frame-wide search\n"
            "  gpa trace value 16.58 --dc 4                    # 2) one draw call\n"
            "  gpa trace value hello --frame 7 --json          # 3) string literal\n"
            "  gpa trace value true                            # 4) boolean\n"
        ),
    )
    p_t_value.add_argument("literal", help="Literal value (e.g. 16.58 or hello)")
    p_t_value.add_argument("--frame", type=int, default=None)
    p_t_value.add_argument("--dc", type=int, default=None)
    p_t_value.add_argument("--json", dest="json_output", action="store_true")

    return parser


def _extract_command(argv: List[str]) -> List[str]:
    """argparse leaves a leading ``--`` in REMAINDER; strip it."""
    if argv and argv[0] == "--":
        return argv[1:]
    return argv


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.cmd == "start":
        return start_cmd.run(
            session_dir=args.session,
            daemon=args.daemon,
            port=args.port,
        )
    if args.cmd == "stop":
        return stop_cmd.run(session_dir=args.session)
    if args.cmd == "env":
        return env_cmd.run(session_dir=args.session)
    if args.cmd == "run":
        cmd = _extract_command(list(args.command or []))
        if not cmd:
            parser.error("run: missing target command (use `--` then the command)")
        return run_cmd.run(
            cmd,
            session_dir=args.session,
            timeout=args.timeout,
            port=args.port,
        )
    if args.cmd == "run-browser":
        return run_browser_cmd.run(
            scenario=args.scenario,
            timeout=args.timeout,
            chromium_path=args.chromium_path,
            keep_open=args.keep_open,
            session_dir=args.session,
            port=args.port,
        )
    if args.cmd == "report":
        only = args.only.split(",") if args.only else None
        skip = args.skip.split(",") if args.skip else None
        return report_cmd.run(
            session_dir=args.session,
            frame=args.frame,
            json_output=args.json_output,
            only=only,
            skip=skip,
        )
    if args.cmd == "check":
        return check_cmd.run(
            name=args.name,
            session_dir=args.session,
            frame=args.frame,
            dc=args.dc,
            json_output=args.json_output,
        )
    if args.cmd == "dump":
        return dump_cmd.run(
            what=args.what,
            session_dir=args.session,
            frame=args.frame,
            x=args.x,
            y=args.y,
            fmt=args.fmt,
        )
    if args.cmd == "diff":
        return diff_cmd.run(args)
    if args.cmd == "frames":
        return frames_cmd.run(args)
    if args.cmd == "drawcalls":
        return drawcalls_cmd.run(args)
    if args.cmd == "pixel":
        return pixel_cmd.run(args)
    if args.cmd == "scene":
        return scene_cmd.run(args)
    if args.cmd == "check-config":
        import sys as _sys
        print(
            "warning: 'gpa check-config' is deprecated; use 'gpa frames check-config'",
            file=_sys.stderr,
        )
        return check_config_cmd.run(
            session_dir=args.session,
            frame=args.frame,
            severity=args.severity,
            rules=args.rules,
            rule=args.rule,
            json_output=args.json_output,
        )
    if args.cmd == "explain-draw":
        print(
            "warning: 'gpa explain-draw' is deprecated; use 'gpa drawcalls explain --dc N'",
            file=sys.stderr,
        )
        return explain_draw_cmd.run(
            draw_id=args.draw_id,
            session_dir=args.session,
            frame=args.frame,
            field=args.field,
            json_output=args.json_output,
            full=args.full,
        )
    if args.cmd == "diff-draws":
        print(
            "warning: 'gpa diff-draws' is deprecated; use 'gpa drawcalls diff --a N --b N'",
            file=sys.stderr,
        )
        return diff_draws_cmd.run(
            a=args.a,
            b=args.b,
            session_dir=args.session,
            frame=args.frame,
            scope=args.scope,
            json_output=args.json_output,
        )
    if args.cmd == "scene-find":
        print(
            "warning: 'gpa scene-find' is deprecated; use 'gpa scene find'",
            file=sys.stderr,
        )
        return scene_find_cmd.run(
            predicates=args.predicates,
            session_dir=args.session,
            frame=args.frame,
            limit=args.limit,
            json_output=args.json_output,
        )
    if args.cmd == "scene-explain":
        print(
            "warning: 'gpa scene-explain' is deprecated; use 'gpa scene explain'",
            file=sys.stderr,
        )
        return scene_explain_cmd.run(
            pixel=args.pixel,
            session_dir=args.session,
            frame=args.frame,
            json_output=args.json_output,
        )
    if args.cmd == "source":
        return source_cmd.run(args)
    if args.cmd == "upstream":
        return upstream_cmd.run(args)
    if args.cmd == "trace":
        if args.trace_cmd == "uniform":
            target = args.name
        elif args.trace_cmd == "value":
            target = args.literal
        else:  # pragma: no cover
            parser.error(f"unknown trace subcommand: {args.trace_cmd!r}")
            return 1
        return trace_cmd.run(
            subcommand=args.trace_cmd,
            target=target,
            frame=args.frame,
            dc=args.dc,
            session_dir=args.session,
            json_output=args.json_output,
        )

    parser.error(f"unknown command: {args.cmd}")  # pragma: no cover
    return 1


if __name__ == "__main__":
    sys.exit(main())
