"""Verify evaluation scenarios and quarantine broken ones.

Layered checks (cheapest first):

  static  — scenario.md parses, fix block has the required fields,
            fix_parent_sha is set when an upstream snapshot is implied,
            files list has ≥1 source-like entry, main.c (if present)
            doesn't leak ground-truth via hint comments.
  network — fix_sha + fix_parent_sha both exist on GitHub
            (gh api repos/<o>/<r>/commits/<sha>).
  build   — runnable scenarios (those with a main.c) build cleanly
            via Bazel using the new nested-taxonomy target path.

A scenario passes only if every requested tier passes. Failed
scenarios are marked ``status: quarantined`` in their scenario.yaml
with a ``verification:`` block summarising what failed; if
``--quarantine-dir`` is set, their directories are physically moved
under that root so :class:`gpa.eval.scenario.ScenarioLoader` (which
walks ``tests/eval``) can't accidentally serve a broken scenario to
the harness.

Usage:
    python -m gpa.eval.curation.verify tests/eval                          # static only, in-place
    python -m gpa.eval.curation.verify tests/eval --network --build        # all checks, in-place
    python -m gpa.eval.curation.verify tests/eval --quarantine-dir tests/eval-quarantine
"""
from __future__ import annotations

import argparse
import dataclasses
import datetime as _dt
import json
import logging
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

import yaml

from gpa.eval.scenario import ScenarioLoader, ScenarioMetadata

_LOG = logging.getLogger(__name__)

_FIX_SECTION_RE = re.compile(
    r"^##\s+Fix\s*\n(.+?)(?=\n##\s+|\Z)",
    re.MULTILINE | re.DOTALL,
)
_YAML_BLOCK_RE = re.compile(r"```yaml\s*\n(.*?)\n```", re.DOTALL)
_REPO_RE = re.compile(r"github\.com/([^/]+)/([^/]+?)(?:/|$)")


@dataclasses.dataclass
class VerificationResult:
    scenario_id: str
    scenario_dir: Path
    failures: list[str] = dataclasses.field(default_factory=list)
    checks_run: list[str] = dataclasses.field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.failures


# ---------------------------------------------------------------------------
# Tier 1: static — scenario.md / scenario.yaml shape only, no I/O
# ---------------------------------------------------------------------------


_FIX_HEADING_RE = re.compile(r"^##\s+Fix\s*$", re.MULTILINE)
_UPSTREAM_HEADING_RE = re.compile(r"^##\s+Upstream Snapshot\s*$", re.MULTILINE)
_BUG_SIG_HEADING_RE = re.compile(r"^##\s+Bug Signature\s*$", re.MULTILINE)
_GROUND_TRUTH_HEADING_RE = re.compile(r"^##\s+Ground Truth\s*$", re.MULTILINE)
# Matches inline hint comments commonly used in early-round scenarios:
# "// BUG", "// BUGGY", "// FIX:", "// should be", "// Correct", etc.
# Kept narrow to avoid matching legitimate code comments.
_SOURCE_HINT_RE = re.compile(
    r"//\s*(?:BUG(?:GY)?|FIX(?:ME)?|HINT|TODO\s+FIX|"
    r"should\s+be|Correct(?:\s+would|\s+is)?|expected|"
    r"actual\s+vs\s+expected)\b",
    re.IGNORECASE,
)
_SOURCE_EXTS = (".c", ".h", ".cpp", ".glsl", ".vert", ".frag")

# Treat parenthesised "(none — ...)" or bare "(none)" as placeholders.
# Some legacy `bug_class: legacy` fix blocks use these instead of leaving
# the field absent; without this check the field-presence rule
# misclassifies them as filled.
_PLACEHOLDER_RE = re.compile(r"^\s*\(\s*none\b", re.IGNORECASE)


def _is_placeholder(value: object) -> bool:
    return isinstance(value, str) and bool(_PLACEHOLDER_RE.match(value))


def _parse_fix_block(scenario_md: Path) -> tuple[Optional[dict], bool]:
    """Extract the ```yaml fix block from scenario.md's ``## Fix`` section.

    Returns ``(parsed_dict, fix_section_present)``. The flag is True when
    the document contains a ``## Fix`` heading, regardless of whether
    its yaml body is well-formed — used by the caller to distinguish
    "legacy scenario with no fix section" (= soft-pass) from "malformed
    fix section" (= hard-fail).

    Critically, the yaml block is searched ONLY within the ``## Fix``
    section. Scenarios sometimes carry an unrelated ``## Bug Signature``
    yaml block earlier in the document; matching that instead would
    surface confusing "fix block missing fix_pr_url" errors.
    """
    text = scenario_md.read_text(encoding="utf-8")
    section_m = _FIX_SECTION_RE.search(text)
    if not section_m:
        return None, False  # no `## Fix` heading at all
    section_body = section_m.group(1)
    yaml_m = _YAML_BLOCK_RE.search(section_body)
    if not yaml_m:
        return None, True  # heading present, body malformed
    try:
        data = yaml.safe_load(yaml_m.group(1))
    except yaml.YAMLError:
        return None, True
    return (data if isinstance(data, dict) else None), True


def _scan_source_contamination(scenario_dir: Path) -> Optional[str]:
    """Look only for hint comments in source files. Independent of
    scenario.md structure — schema-mismatch is not contamination."""
    for ext in _SOURCE_EXTS:
        for src in scenario_dir.rglob(f"*{ext}"):
            try:
                text = src.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            m = _SOURCE_HINT_RE.search(text)
            if m:
                line = text[:m.start()].count("\n") + 1
                return (
                    f"{src.relative_to(scenario_dir)}: hint comment "
                    f"'{m.group(0)}' (line {line})"
                )
    return None


def _check_static(scenario_dir: Path) -> list[str]:
    failures: list[str] = []
    md = scenario_dir / "scenario.md"
    if not md.is_file():
        return ["scenario.md missing"]

    text = md.read_text(encoding="utf-8")
    has_anchor = (
        _FIX_HEADING_RE.search(text)
        or _UPSTREAM_HEADING_RE.search(text)
        or _BUG_SIG_HEADING_RE.search(text)
        or _GROUND_TRUTH_HEADING_RE.search(text)
    )
    if not has_anchor:
        # No ground-truth anchor at all — no `## Fix` (mined scenarios),
        # no `## Upstream Snapshot` (advisor-mode), no `## Bug Signature`
        # (synthetic + framebuffer matcher), no `## Ground Truth` (prose
        # ground truth for early-round hand-authored scenarios). Nothing
        # for the harness to score against.
        failures.append(
            "scenario.md has no ground-truth anchor "
            "(## Fix / ## Upstream Snapshot / ## Bug Signature / ## Ground Truth)"
        )

    fix, has_fix_heading = _parse_fix_block(md)

    if has_fix_heading and fix is None:
        # The author included a `## Fix` section but the yaml body is
        # malformed — that's a real defect, not a schema mismatch.
        failures.append("## Fix section present but yaml block missing or unparseable")
    elif fix is not None:
        # Fix block present — every required field must be set.
        fix_pr_url = fix.get("fix_pr_url")
        fix_sha = fix.get("fix_sha")
        fix_parent_sha = fix.get("fix_parent_sha")
        bug_class = fix.get("bug_class")
        files = fix.get("files") or []

        is_legacy = str(bug_class) == "legacy"
        # `bug_class: legacy` is a documented escape hatch for scenarios
        # retained without a resolvable fix-PR (issue closed as wontfix
        # / classified as a known limitation). Empty files + missing
        # SHAs are tolerated for that class only.

        if not bug_class:
            failures.append("fix block missing bug_class")
        if not is_legacy:
            if not fix_pr_url or _is_placeholder(fix_pr_url):
                failures.append("fix block missing fix_pr_url")
            if not fix_sha or _is_placeholder(fix_sha):
                failures.append("fix block missing fix_sha")
            if not files:
                failures.append("fix block has empty files list")
            # fix_parent_sha is required whenever the fix points at a
            # github repo — without it the loader falls back to fix_sha
            # and the snapshot serves the post-fix (bug-already-removed)
            # state.
            if (fix_pr_url and "github.com" in str(fix_pr_url)
                    and (not fix_parent_sha or _is_placeholder(fix_parent_sha))):
                failures.append(
                    "fix_parent_sha unset (snapshot would default to "
                    "post-fix state)"
                )

    # Source contamination is checked independently of the fix section —
    # legacy scenarios with `## Upstream Snapshot` (no `## Fix`) are
    # still subject to the "no hint comments" rule.
    contamination = _scan_source_contamination(scenario_dir)
    if contamination:
        failures.append(f"source contamination: {contamination}")

    return failures


# ---------------------------------------------------------------------------
# Tier 2: network — verify SHAs resolve on github
# ---------------------------------------------------------------------------


def _gh_commit_exists(owner: str, repo: str, sha: str) -> bool:
    try:
        subprocess.run(
            ["gh", "api", f"repos/{owner}/{repo}/commits/{sha}"],
            capture_output=True, text=True, check=True, timeout=30,
        )
        return True
    except (subprocess.SubprocessError, OSError):
        return False


def _check_network(scenario_dir: Path) -> list[str]:
    failures: list[str] = []
    fix = _parse_fix_block(scenario_dir / "scenario.md") or {}
    fix_pr_url = fix.get("fix_pr_url") or ""
    repo_m = _REPO_RE.search(fix_pr_url)
    if not repo_m:
        return failures  # static check already flagged a missing/invalid url
    owner, repo = repo_m.group(1), repo_m.group(2)

    fix_sha = fix.get("fix_sha")
    parent_sha = fix.get("fix_parent_sha")
    if fix_sha and not _gh_commit_exists(owner, repo, fix_sha):
        failures.append(f"fix_sha {fix_sha[:10]} not found on github")
    if parent_sha and not _gh_commit_exists(owner, repo, parent_sha):
        failures.append(f"fix_parent_sha {parent_sha[:10]} not found on github")
    return failures


# ---------------------------------------------------------------------------
# Tier 3: build — Bazel build for runnable scenarios
# ---------------------------------------------------------------------------


def _check_build(scenario: ScenarioMetadata, repo_root: Path,
                 bazel: str = "bazel") -> list[str]:
    if not scenario.source_path:
        # Mined scenario without a synthetic reproducer — there's nothing
        # to build. That's a legitimate state for advisor-mode scenarios.
        return []
    src = Path(scenario.source_path)
    try:
        pkg = src.parent.relative_to(repo_root)
    except ValueError:
        return [f"source_path {src} not under repo_root {repo_root}"]
    target = f"//{pkg.as_posix()}:{scenario.binary_name}"
    try:
        proc = subprocess.run(
            [bazel, "build", target],
            cwd=str(repo_root), capture_output=True, text=True, timeout=180,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        return [f"bazel build invocation failed: {exc}"]
    if proc.returncode != 0:
        # Truncate stderr to keep the verification block readable
        err = (proc.stderr or "").strip().splitlines()
        tail = err[-3:] if err else []
        return [f"bazel build failed: {' | '.join(tail)}"]
    return []


# ---------------------------------------------------------------------------
# Persisting the verdict + quarantining
# ---------------------------------------------------------------------------


def _write_verdict(scenario_dir: Path, result: VerificationResult) -> None:
    """Update scenario.yaml's status + verification block in place."""
    yml_path = scenario_dir / "scenario.yaml"
    data: dict
    if yml_path.exists():
        try:
            data = yaml.safe_load(yml_path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            data = {}
    else:
        data = {}
    if not isinstance(data, dict):
        data = {}

    data["status"] = "verified" if result.passed else "quarantined"
    data["verification"] = {
        "checked_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "checks_run": list(result.checks_run),
        "failures": list(result.failures),
    }
    yml_path.write_text(
        yaml.safe_dump(data, sort_keys=False), encoding="utf-8"
    )


def _quarantine(scenario_dir: Path, *, eval_root: Path,
                quarantine_dir: Path) -> Path:
    """Move ``scenario_dir`` to the mirror path under ``quarantine_dir``.

    Returns the new path. Idempotent: if the destination already exists,
    raises FileExistsError so we don't silently merge two scenarios.
    """
    rel = scenario_dir.relative_to(eval_root)
    dest = quarantine_dir / rel
    if dest.exists():
        raise FileExistsError(f"quarantine destination already exists: {dest}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(scenario_dir), str(dest))
    return dest


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def verify_scenario(
    scenario_dir: Path,
    *,
    eval_root: Path,
    repo_root: Path,
    network: bool = False,
    build: bool = False,
    bazel: str = "bazel",
) -> VerificationResult:
    sid = scenario_dir.name
    result = VerificationResult(scenario_id=sid, scenario_dir=scenario_dir)

    result.checks_run.append("static")
    result.failures.extend(_check_static(scenario_dir))

    # Skip downstream tiers when static failed — their failures would be
    # noise rather than signal (e.g. a missing fix_sha will trip every
    # network/build check identically).
    if not result.failures and network:
        result.checks_run.append("network")
        result.failures.extend(_check_network(scenario_dir))

    if not result.failures and build:
        result.checks_run.append("build")
        try:
            scenario = ScenarioLoader(eval_dir=str(eval_root)).load(sid)
        except Exception as exc:
            result.failures.append(f"loader failed: {exc}")
        else:
            result.failures.extend(_check_build(scenario, repo_root, bazel))

    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify eval scenarios and quarantine broken ones.",
    )
    parser.add_argument("root", type=Path,
                        help="Eval root to walk (typically tests/eval)")
    parser.add_argument("--network", action="store_true",
                        help="Verify fix_sha + fix_parent_sha on github (slow)")
    parser.add_argument("--build", action="store_true",
                        help="Run `bazel build` per runnable scenario (slow)")
    parser.add_argument("--quarantine-dir", type=Path, default=None,
                        help="Move failed scenarios under this dir (mirrors "
                        "the original taxonomy path). Without this flag, "
                        "failures are recorded in scenario.yaml only.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Compute verdicts but don't update scenario.yaml "
                        "or move directories")
    parser.add_argument("--bazel", default="bazel",
                        help="bazel binary (default: 'bazel')")
    parser.add_argument("--repo-root", type=Path, default=None,
                        help="Repo root (auto-detected from MODULE.bazel if "
                        "omitted)")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO,
                        format="%(levelname)s %(name)s: %(message)s")

    if not args.root.is_dir():
        print(f"ERROR: not a directory: {args.root}", file=sys.stderr)
        return 2

    repo_root = args.repo_root
    if repo_root is None:
        # Walk up from args.root looking for MODULE.bazel
        for parent in [args.root, *args.root.parents]:
            if (parent / "MODULE.bazel").exists() or (parent / "WORKSPACE").exists():
                repo_root = parent
                break
        else:
            repo_root = Path.cwd()
    repo_root = repo_root.resolve()

    eval_root = args.root.resolve()

    results: list[VerificationResult] = []
    for md in sorted(eval_root.rglob("scenario.md")):
        sd = md.parent
        result = verify_scenario(
            sd,
            eval_root=eval_root,
            repo_root=repo_root,
            network=args.network,
            build=args.build,
            bazel=args.bazel,
        )
        results.append(result)
        verdict = "PASS" if result.passed else "FAIL"
        print(f"{verdict:4s} {sd.relative_to(eval_root)}: "
              f"{', '.join(result.failures) if result.failures else 'ok'}")

    if not args.dry_run:
        for result in results:
            _write_verdict(result.scenario_dir, result)
        if args.quarantine_dir:
            qdir = args.quarantine_dir.resolve()
            qdir.mkdir(parents=True, exist_ok=True)
            for result in results:
                if result.passed:
                    continue
                try:
                    new_path = _quarantine(
                        result.scenario_dir,
                        eval_root=eval_root, quarantine_dir=qdir,
                    )
                    print(f"   quarantined → {new_path.relative_to(qdir.parent)}")
                except FileExistsError as exc:
                    print(f"   skip move: {exc}")

    n_pass = sum(1 for r in results if r.passed)
    n_fail = len(results) - n_pass
    print(f"\ntotal: {len(results)}, pass: {n_pass}, fail: {n_fail}")
    if args.dry_run:
        print("(dry run — scenario.yaml not updated, no files moved)")
    return 0 if n_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
