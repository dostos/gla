"""``gpa check-config`` — flag framework-config bugs visible in GL state.

Calls ``GET /api/v1/frames/<id>/check-config`` and renders findings
either as plain text (default) or JSON. Read-only, idempotent.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from gpa.cli.rest_client import RestClient, RestError
from gpa.cli.session import Session


# --------------------------------------------------------------------------- #
# Subparser
# --------------------------------------------------------------------------- #


def add_subparser(subparsers) -> None:
    """Register ``check-config`` on the parent CLI ``subparsers``."""
    epilog = (
        "Examples:\n"
        "  gpa check-config                              "
        "# latest frame, default warn threshold\n"
        "  gpa check-config --frame 142 --json           "
        "# specific frame, machine-readable\n"
        "  gpa check-config --severity error             "
        "# only errors\n"
        "  gpa check-config --rule "
        "color-space-encoding-mismatch,tone-mapping-on-non-float-target\n"
        "  gpa check-config --rules                      "
        "# list available rules\n"
        "  gpa frames | gpa check-config --frame -       "
        "# pipeline\n"
    )
    import argparse
    p = subparsers.add_parser(
        "check-config",
        help="Cross-validate captured GL state against framework-config rules",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=epilog,
    )
    p.add_argument(
        "--session", dest="session", type=Path, default=None,
        help="Session directory (overrides $GPA_SESSION and the link)",
    )
    p.add_argument(
        "--frame", dest="frame", default=None,
        help="Frame id (default: latest). Use '-' to read ids from stdin.",
    )
    p.add_argument(
        "--severity", default="warn",
        choices=("error", "warn", "info"),
        help="Minimum severity to report (default: warn)",
    )
    p.add_argument(
        "--rules", action="store_true",
        help="List all known rules with severity + 1-line description, then exit",
    )
    p.add_argument(
        "--rule", default=None,
        help="Comma-separated rule ids to run (default: all enabled)",
    )
    p.add_argument(
        "--json", dest="json_output", action="store_true",
        help="Emit machine-readable JSON instead of plain text",
    )


# --------------------------------------------------------------------------- #
# Rendering helpers
# --------------------------------------------------------------------------- #


_SEV_TAG = {"error": "ERROR", "warn": "WARN", "info": "INFO"}


def _format_human(payload: Dict[str, Any]) -> str:
    findings: List[Dict[str, Any]] = list(payload.get("findings") or [])
    rules_evaluated: List[str] = list(payload.get("rules_evaluated") or [])
    frame_id = payload.get("frame_id")
    lines: List[str] = []
    lines.append(
        f"gpa check-config — frame {frame_id} "
        f"({len(rules_evaluated)} rules evaluated)"
    )
    if not findings:
        lines.append("0 findings.")
        return "\n".join(lines) + "\n"

    sev_counts: Dict[str, int] = {}
    for f in findings:
        sev = f.get("severity", "info")
        sev_counts[sev] = sev_counts.get(sev, 0) + 1
    summary = ", ".join(
        f"{sev_counts[s]} {s}" for s in ("error", "warn", "info") if s in sev_counts
    )
    lines.append(f"{len(findings)} finding(s): {summary}")
    lines.append("")

    for f in findings:
        sev = f.get("severity", "info")
        tag = _SEV_TAG.get(sev, sev.upper())
        rid = f.get("rule_id", "?")
        msg = (f.get("message") or "").strip()
        # Squeeze whitespace.
        msg = " ".join(msg.split())
        lines.append(f"[{tag}] {rid}: {msg}")
        hint = (f.get("hint") or "").strip()
        if hint:
            hint = " ".join(hint.split())
            lines.append(f"           hint: {hint}")
        evidence = f.get("evidence") or {}
        if evidence:
            lines.append(f"           evidence: {json.dumps(evidence, sort_keys=True)}")
    return "\n".join(lines) + "\n"


def _format_json(payload: Dict[str, Any]) -> str:
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


# --------------------------------------------------------------------------- #
# --rules listing — does not need a live engine session.
# --------------------------------------------------------------------------- #


def _print_rules_listing(json_output: bool, print_stream) -> int:
    """Print the rule catalogue from in-process YAML; no REST call."""
    from gpa.checks import default_engine
    eng = default_engine()
    rules = []
    for r in eng.all_rules():
        rules.append({
            "id": r.id,
            "severity": r.severity,
            "default_enabled": r.enabled_by_default,
            "description": " ".join((r.message_template or "").split()),
        })
    if json_output:
        print_stream.write(json.dumps({"rules": rules}, indent=2) + "\n")
    else:
        print_stream.write("Available rules:\n")
        for r in rules:
            tag = _SEV_TAG.get(r["severity"], r["severity"].upper())
            mark = "" if r["default_enabled"] else "  (disabled by default)"
            desc = r["description"]
            if len(desc) > 100:
                desc = desc[:97] + "..."
            print_stream.write(f"  [{tag:5s}] {r['id']}{mark}\n           {desc}\n")
    print_stream.flush()
    return 0


# --------------------------------------------------------------------------- #
# Frame-id resolution
# --------------------------------------------------------------------------- #


def _resolve_frames(
    raw_flag: Optional[str], stdin_stream
) -> List[Optional[int]]:
    """Return a list of frame ids to query.

    - ``raw_flag`` is the literal string from --frame, or ``None``.
    - If ``raw_flag`` == "-", read newline-separated ints from stdin
      (skipping blanks).
    - If ``raw_flag`` is a valid int, use that.
    - If ``raw_flag`` is None and stdin is a TTY, return [None] to mean
      "latest".
    - If ``raw_flag`` is None and stdin is piped, treat stdin as an id list.
    """
    if raw_flag == "-":
        ids = []
        for line in stdin_stream:
            line = line.strip()
            if not line:
                continue
            try:
                ids.append(int(line))
            except ValueError:
                continue
        if not ids:
            # Empty stdin -> default to latest.
            return [None]
        return list(ids)
    if raw_flag is not None:
        try:
            return [int(raw_flag)]
        except ValueError:
            return [None]  # caller will report an error
    # No --frame, no stdin marker: peek at stdin.
    try:
        is_tty = stdin_stream.isatty()
    except (AttributeError, ValueError):
        is_tty = True
    if not is_tty:
        ids = []
        for line in stdin_stream:
            line = line.strip()
            if not line:
                continue
            try:
                ids.append(int(line))
            except ValueError:
                continue
        if ids:
            return list(ids)
    return [None]


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #


def run(
    *,
    session_dir: Optional[Path] = None,
    frame: Optional[str] = None,
    severity: str = "warn",
    rules: bool = False,
    rule: Optional[str] = None,
    json_output: bool = False,
    client: Optional[RestClient] = None,
    print_stream=None,
    stdin_stream=None,
) -> int:
    """Run ``gpa check-config``. Returns the exit code per spec §2.2."""
    if print_stream is None:
        print_stream = sys.stdout
    if stdin_stream is None:
        stdin_stream = sys.stdin

    # ---- --rules: shortcut, no session needed ----
    if rules:
        return _print_rules_listing(json_output, print_stream)

    # ---- Validate severity ----
    if severity not in {"error", "warn", "info"}:
        print(
            f"Error: unknown severity '{severity}'.\n"
            "  gpa check-config --severity error|warn|info",
            file=sys.stderr,
        )
        return 3

    # ---- Validate rule names locally so we can fail fast ----
    rule_ids: List[str] = []
    if rule:
        rule_ids = [r.strip() for r in rule.split(",") if r.strip()]
        from gpa.checks import default_engine
        known = set(default_engine().rule_ids())
        for rid in rule_ids:
            if rid not in known:
                print(
                    f"Error: unknown rule '{rid}'.\n"
                    "  gpa check-config --rules    # list available rule ids",
                    file=sys.stderr,
                )
                return 3

    # ---- Frame id source ----
    if frame is not None and frame != "-":
        try:
            int(frame)
        except ValueError:
            print(
                f"Error: --frame must be an integer or '-', got {frame!r}.\n"
                "  gpa check-config --frame 142",
                file=sys.stderr,
            )
            return 3

    frames = _resolve_frames(frame, stdin_stream)

    # ---- Resolve session ----
    sess = Session.discover(explicit=session_dir)
    if sess is None:
        print(
            "Error: no active GPA session. Run 'gpa start' first.",
            file=sys.stderr,
        )
        return 3

    if client is None:
        try:
            client = RestClient.from_session(sess)
        except Exception as exc:  # noqa: BLE001
            print(f"[gpa] failed to connect to engine: {exc}", file=sys.stderr)
            return 1

    # ---- Hit the endpoint per frame ----
    overall_exit = 0
    aggregated: List[Dict[str, Any]] = []
    for fid in frames:
        path = (
            f"/api/v1/frames/latest/check-config"
            if fid is None else
            f"/api/v1/frames/{int(fid)}/check-config"
        )
        params: List[str] = [f"severity={severity}"]
        for rid in rule_ids:
            params.append(f"rule={rid}")
        if params:
            path = path + "?" + "&".join(params)
        try:
            payload = client.get_json(path)
        except RestError as exc:
            print(f"[gpa] {exc}", file=sys.stderr)
            return 1

        if not isinstance(payload, dict):
            print(f"[gpa] unexpected response shape: {type(payload).__name__}",
                  file=sys.stderr)
            return 1

        if json_output:
            aggregated.append(payload)
        else:
            print_stream.write(_format_human(payload))

        if (payload.get("findings") or []):
            overall_exit = max(overall_exit, 2)

    if json_output:
        if len(aggregated) == 1:
            print_stream.write(_format_json(aggregated[0]))
        else:
            print_stream.write(_format_json({"frames": aggregated}))
    print_stream.flush()
    return overall_exit
