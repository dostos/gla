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
from gpa.cli.commands import annotate as annotate_cmd
from gpa.cli.commands import annotations as annotations_cmd
from gpa.cli.commands import check as check_cmd
from gpa.cli.commands import check_config as check_config_cmd
from gpa.cli.commands import diff_draws as diff_draws_cmd
from gpa.cli.commands import dump as dump_cmd
from gpa.cli.commands import env as env_cmd
from gpa.cli.commands import explain_draw as explain_draw_cmd
from gpa.cli.commands import frames as frames_cmd
from gpa.cli.commands import report as report_cmd
from gpa.cli.commands import run as run_cmd
from gpa.cli.commands import run_browser as run_browser_cmd
from gpa.cli.commands import scene_explain as scene_explain_cmd
from gpa.cli.commands import scene_find as scene_find_cmd
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

    p_start = sub.add_parser("start", help="Start a persistent engine session")
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

    p_stop = sub.add_parser("stop", help="Terminate the active session")
    _add_session_arg(p_stop)

    p_env = sub.add_parser("env", help="Print env exports for the active session")
    _add_session_arg(p_env)

    p_run = sub.add_parser(
        "run",
        help="Launch a target under an embedded engine + shim",
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
    )
    _add_session_arg(p_check)
    p_check.add_argument("name", help="Check name (e.g. feedback-loops)")
    p_check.add_argument("--frame", type=int, default=None)
    p_check.add_argument("--dc", type=int, default=None,
                         help="Filter to a single draw call id")
    p_check.add_argument("--json", dest="json_output", action="store_true")

    # ---- dump -------------------------------------------------------------
    p_dump = sub.add_parser("dump", help="Raw REST data access")
    _add_session_arg(p_dump)
    p_dump.add_argument("what", help="frame | drawcalls | drawcall | shader | "
                                     "textures | attachments | pixel")
    p_dump.add_argument("--frame", type=int, default=None)
    p_dump.add_argument("--dc", type=int, default=None)
    p_dump.add_argument("--x", type=int, default=None)
    p_dump.add_argument("--y", type=int, default=None)
    p_dump.add_argument("--format", dest="fmt", default="plain",
                        choices=["plain", "json", "compact"])

    # ---- frames -----------------------------------------------------------
    p_frames = sub.add_parser("frames", help="List captured frame ids")
    _add_session_arg(p_frames)
    p_frames.add_argument(
        "--json", dest="json_output", action="store_true",
        help="Emit JSON ({\"frames\":[…]}) instead of one id per line",
    )

    # ---- check-config -----------------------------------------------------
    check_config_cmd.add_subparser(sub)

    # ---- bidirectional narrow scene↔GL queries ----------------------------
    explain_draw_cmd.add_subparser(sub)
    diff_draws_cmd.add_subparser(sub)
    scene_find_cmd.add_subparser(sub)
    scene_explain_cmd.add_subparser(sub)

    # ---- annotate ---------------------------------------------------------
    p_annotate = sub.add_parser(
        "annotate",
        help="POST KEY=VALUE annotation pairs to a frame",
    )
    _add_session_arg(p_annotate)
    p_annotate.add_argument("--frame", type=int, required=True)
    p_annotate.add_argument("pairs", nargs="+", help="KEY=VALUE pairs")

    # ---- annotations ------------------------------------------------------
    p_ann = sub.add_parser(
        "annotations",
        help="Retrieve the annotation payload for a frame",
    )
    _add_session_arg(p_ann)
    p_ann.add_argument("--frame", type=int, required=True)

    # ---- trace ------------------------------------------------------------
    p_trace = sub.add_parser(
        "trace",
        help=(
            "Reverse-lookup a captured value → app-level JS fields that hold it. "
            "Requires the WebGL shim (gpa-trace.js) to be enabled in the target."
        ),
    )
    _add_session_arg(p_trace)
    trace_sub = p_trace.add_subparsers(dest="trace_cmd", required=True)

    p_t_uniform = trace_sub.add_parser(
        "uniform", help="Trace a uniform by name (requires --dc)"
    )
    p_t_uniform.add_argument("name", help="Uniform name (e.g. uZoom)")
    p_t_uniform.add_argument("--frame", type=int, default=None)
    p_t_uniform.add_argument("--dc", type=int, default=None)
    p_t_uniform.add_argument("--json", dest="json_output", action="store_true")

    p_t_texture = trace_sub.add_parser(
        "texture", help="Trace a texture id (requires --dc)"
    )
    p_t_texture.add_argument("tex_id", type=int, help="GL texture object id")
    p_t_texture.add_argument("--frame", type=int, default=None)
    p_t_texture.add_argument("--dc", type=int, default=None)
    p_t_texture.add_argument("--json", dest="json_output", action="store_true")

    p_t_value = trace_sub.add_parser(
        "value",
        help="Trace a literal value (number/string/bool) across the frame",
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
            dc=args.dc,
            x=args.x,
            y=args.y,
            fmt=args.fmt,
        )
    if args.cmd == "frames":
        return frames_cmd.run(
            session_dir=args.session,
            json_output=args.json_output,
        )
    if args.cmd == "check-config":
        return check_config_cmd.run(
            session_dir=args.session,
            frame=args.frame,
            severity=args.severity,
            rules=args.rules,
            rule=args.rule,
            json_output=args.json_output,
        )
    if args.cmd == "explain-draw":
        return explain_draw_cmd.run(
            draw_id=args.draw_id,
            session_dir=args.session,
            frame=args.frame,
            field=args.field,
            json_output=args.json_output,
            full=args.full,
        )
    if args.cmd == "diff-draws":
        return diff_draws_cmd.run(
            a=args.a,
            b=args.b,
            session_dir=args.session,
            frame=args.frame,
            scope=args.scope,
            json_output=args.json_output,
        )
    if args.cmd == "scene-find":
        return scene_find_cmd.run(
            predicates=args.predicates,
            session_dir=args.session,
            frame=args.frame,
            limit=args.limit,
            json_output=args.json_output,
        )
    if args.cmd == "scene-explain":
        return scene_explain_cmd.run(
            pixel=args.pixel,
            session_dir=args.session,
            frame=args.frame,
            json_output=args.json_output,
        )
    if args.cmd == "annotate":
        return annotate_cmd.run(
            frame=args.frame,
            pairs=args.pairs,
            session_dir=args.session,
        )
    if args.cmd == "annotations":
        return annotations_cmd.run(
            frame=args.frame,
            session_dir=args.session,
        )
    if args.cmd == "trace":
        if args.trace_cmd == "uniform":
            target = args.name
        elif args.trace_cmd == "texture":
            target = str(args.tex_id)
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
