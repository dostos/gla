"""Main orchestrator for the OpenGPA evaluation harness."""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Optional

_log = logging.getLogger(__name__)

from gpa.eval.metrics import DiagnosisScorer, EvalResult
from gpa.eval.runner import ScenarioRunner
from gpa.eval.scenario import ScenarioLoader, ScenarioMetadata

if TYPE_CHECKING:
    from gpa.eval.snapshot_fetcher import SnapshotFetcher

# Callable signature: (scenario, mode, tools) -> (diagnosis_text, input_tokens,
#   output_tokens, tool_calls, num_turns, time_seconds)
AgentFn = Callable[
    [ScenarioMetadata, str, dict],
    tuple[str, int, int, int, int, float],
]

_ALL_MODES = ["with_gla", "code_only"]

_SNAPSHOT_MAX_BYTES = 200 * 1024  # 200 KB


class EvalHarness:
    """Orchestrates eval runs across scenarios and modes."""

    def __init__(self, config: Optional[dict] = None,
                 snapshot_fetcher: Optional["SnapshotFetcher"] = None):
        cfg = config or {}
        eval_dir = cfg.get("eval_dir", "tests/eval")
        self.loader = ScenarioLoader(eval_dir=eval_dir)
        self.runner = ScenarioRunner(
            gpa_base_url=cfg.get("gpa_base_url", "http://127.0.0.1:18080"),
            gpa_token=cfg.get("gpa_token", ""),
            shim_path=cfg.get("shim_path", ""),
            bazel_bin=cfg.get("bazel_bin", "bazel"),
            repo_root=cfg.get("repo_root"),
        )
        self._scorer = DiagnosisScorer(
            diagnosis_threshold=cfg.get("diagnosis_threshold", 0.25),
            fix_threshold=cfg.get("fix_threshold", 0.25),
        )
        self._model = cfg.get("model", "unknown")
        self.results: list[EvalResult] = []
        self._snapshot_fetcher = snapshot_fetcher

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run_scenario(
        self,
        scenario_id: str,
        mode: str,
        agent_fn: AgentFn,
    ) -> EvalResult:
        """Run one scenario in one mode.

        Args:
            scenario_id: e.g. "e1_state_leak"
            mode: "with_gla" or "code_only"
            agent_fn: callable(scenario, mode, tools) ->
                      (diagnosis_text, input_tokens, output_tokens,
                       tool_calls, num_turns, time_seconds)

        Returns:
            EvalResult with scores populated.
        """
        if mode not in _ALL_MODES:
            raise ValueError(f"mode must be one of {_ALL_MODES}, got: {mode!r}")

        scenario = self.loader.load(scenario_id)

        # Build tool set for the agent
        tools = self._build_tools(scenario, mode)

        # Invoke the agent
        (
            diagnosis_text,
            input_tokens,
            output_tokens,
            tool_calls,
            num_turns,
            elapsed,
        ) = agent_fn(scenario, mode, tools)

        # Legacy keyword scorer — still runs so we can compare.
        correct_diag, correct_fix = self._scorer.score(diagnosis_text, scenario)

        # Maintainer-framing scorer (Phase 4): run when the scenario has
        # a parseable `## Fix` section with a non-legacy bug_class that
        # targets file-level scoring.  The scorer is best-effort: any
        # error degrades gracefully (fields stay None).
        bug_class = tools.get("bug_class")
        maintainer_solved: Optional[bool] = None
        file_score: Optional[float] = None
        file_hits: Optional[list] = None
        file_misses: Optional[list] = None
        file_extras: Optional[list] = None
        out_of_tree: Optional[list] = None
        parsed_json: Optional[bool] = None

        if bug_class == "framework-internal" and scenario.fix is not None:
            try:
                from gpa.eval.scorer import (
                    _extract_json_tail, score_maintainer_patch,
                )
                # Parse JSON tail separately from scoring so we can track
                # parsed_json independently (missing JSON → timeout per
                # telemetry.classify_verdict).
                parsed = _extract_json_tail(diagnosis_text)
                parsed_json = parsed is not None
                snapshot_root = None
                try:
                    if (scenario.upstream_snapshot_repo
                            and scenario.upstream_snapshot_sha):
                        snapshot_root = self._ensure_snapshot(scenario)
                except Exception:
                    snapshot_root = None
                sr = score_maintainer_patch(
                    parsed if parsed is not None else diagnosis_text,
                    scenario.fix,
                    snapshot_root=snapshot_root,
                )
                maintainer_solved = sr.solved
                file_score = sr.file_score
                file_hits = list(sr.file_hits)
                file_misses = list(sr.file_misses)
                file_extras = list(sr.file_extras)
                out_of_tree = list(sr.out_of_tree)
            except Exception:
                # Scoring is best-effort; don't fail the run on scorer bugs.
                pass

        result = EvalResult(
            scenario_id=scenario_id,
            mode=mode,
            correct_diagnosis=correct_diag,
            correct_fix=correct_fix,
            diagnosis_text=diagnosis_text,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
            tool_calls=tool_calls,
            num_turns=num_turns,
            time_seconds=elapsed,
            model=self._model,
            timestamp=datetime.now(timezone.utc).isoformat(),
            bug_class=bug_class,
            maintainer_solved=maintainer_solved,
            file_score=file_score,
            file_hits=file_hits,
            file_misses=file_misses,
            file_extras=file_extras,
            out_of_tree=out_of_tree,
            parsed_json=parsed_json,
        )
        self.results.append(result)
        return result

    def run_all(
        self,
        agent_fn: AgentFn,
        scenarios: Optional[list[str]] = None,
        modes: Optional[list[str]] = None,
    ) -> list[EvalResult]:
        """Run all (or a subset of) scenarios in all (or subset of) modes.

        Args:
            agent_fn: see run_scenario
            scenarios: list of scenario IDs; None means all available
            modes: list of modes; None means ["with_gla", "code_only"]

        Returns:
            All EvalResult objects produced in this run.
        """
        if scenarios is None:
            all_meta = self.loader.load_all()
            scenarios = [m.id for m in all_meta]
        if modes is None:
            modes = list(_ALL_MODES)

        new_results: list[EvalResult] = []
        for sid in scenarios:
            for mode in modes:
                result = self.run_scenario(sid, mode, agent_fn)
                new_results.append(result)
        return new_results

    def save_results(self, path: str) -> None:
        """Serialize all accumulated results to a JSON file."""
        data = [r.to_dict() for r in self.results]
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)

    @staticmethod
    def load_results(path: str) -> list[EvalResult]:
        """Load previously-saved results from a JSON file."""
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return [EvalResult.from_dict(d) for d in data]

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _build_tools(self, scenario: ScenarioMetadata, mode: str) -> dict:
        """Return a tool dictionary passed to the agent.

        In 'with_gla' mode the runner tools are included.
        In 'code_only' mode only the source reader is provided.
        When the scenario has upstream snapshot refs, read_upstream,
        list_upstream_files and grep_upstream are added for both modes.
        These are full-repo tools — they walk / read / grep the ENTIRE
        snapshot, not just ``upstream_snapshot_relevant_files`` (which is
        now a hint list per the maintainer-framing spec, not a
        restriction).

        The returned dict also carries two meta entries the agent layer
        uses to drive maintainer-framing prompts and scoring:

        - ``bug_class``: the resolved bug class for this scenario
          (``framework-internal`` | ``consumer-misuse`` | ``user-config``
          | ``legacy``).  Inferred from ``scenario.fix.bug_class`` when
          present; otherwise ``"legacy"``.
        - ``system_prompt``: the rendered system prompt for this
          scenario, chosen by :meth:`_select_prompt_for_scenario` per
          ``bug_class``.  May be ``None`` for legacy scenarios, in which
          case the agent falls back to its existing diagnosis prompt.
        """
        tools: dict = {
            "read_source": lambda: self.runner.read_source(scenario),
            # Directory-form scenarios include extra .c/.h/.glsl/.vert/.frag
            # files beyond main.c. Expose them through a pair of scoped
            # tools that deny any access to scenario.md (which carries
            # Ground Truth). read_source still returns main.c contents for
            # backward compatibility.
            "list_scenario_files": lambda: self._list_scenario_files(scenario),
            "read_scenario_file": lambda path: self._read_scenario_file(scenario, path),
        }
        if mode == "with_gla":
            def _safe_run_with_capture():
                try:
                    return self.runner.run_with_capture(scenario)
                except (RuntimeError, FileNotFoundError, OSError) as exc:
                    _log.warning(
                        "scenario %s: live capture unavailable (%s); "
                        "with_gla will run without GPA_FRAME_ID",
                        scenario.id, exc,
                    )
                    return None
            tools["run_with_capture"] = _safe_run_with_capture

        # Add snapshot tools when the scenario references an upstream snapshot.
        # Agents should be able to walk, read, and grep across the full
        # snapshot — not just the `relevant_files` hint list.
        if scenario.upstream_snapshot_repo and scenario.upstream_snapshot_sha:
            tools["read_upstream"] = lambda path: self._read_snapshot_file(scenario, path)
            tools["list_upstream_files"] = lambda subdir="": self._list_snapshot_files(scenario, subdir)
            tools["grep_upstream"] = lambda pattern, subdir="", glob="", max_matches=200: (
                self._grep_snapshot(scenario, pattern, subdir=subdir,
                                    glob=glob, max_matches=max_matches)
            )

        # Maintainer-framing metadata (Phase 4).  Agents that want to
        # honour bug-class-aware prompting read these two keys; the
        # default ``build_agent_fn`` does exactly that.  Legacy agents
        # can ignore them.
        bug_class = self._resolve_bug_class(scenario)
        tools["bug_class"] = bug_class
        tools["system_prompt"] = self._select_prompt_for_scenario(
            scenario, bug_class=bug_class, mode=mode,
        )

        return tools

    @staticmethod
    def _resolve_bug_class(scenario: ScenarioMetadata) -> str:
        """Return the bug_class for a scenario.

        Falls back to ``"legacy"`` when ``scenario.fix`` is absent or
        carries no bug_class.  This keeps the pre-R10 scenarios on the
        legacy diagnosis prompt even after Phase 4 lands.
        """
        fix = getattr(scenario, "fix", None)
        if fix is not None and getattr(fix, "bug_class", None):
            return str(fix.bug_class)
        return "legacy"

    def _select_prompt_for_scenario(
        self,
        scenario: ScenarioMetadata,
        bug_class: str,
        mode: str,
    ) -> Optional[str]:
        """Render the right prompt for a scenario by bug_class.

        Returns None for ``bug_class == "legacy"`` so the agent falls
        back to its existing diagnosis prompt.
        """
        # Import lazily so harness has no startup dependency on the
        # prompts package (keeps import times cheap for callers that
        # don't need prompts, e.g. analytics scripts).
        from gpa.eval.prompts import load_prompt, render_maintainer_prompt

        if bug_class == "framework-internal":
            return render_maintainer_prompt(
                framework=scenario.framework or "the framework",
                user_report=scenario.bug_description or "",
                upstream_snapshot_repo=scenario.upstream_snapshot_repo,
                upstream_snapshot_sha=scenario.upstream_snapshot_sha,
                mode=mode,
            )
        if bug_class == "consumer-misuse":
            return self._render_class_prompt(
                "advisor", scenario, mode=mode,
            )
        if bug_class == "user-config":
            return self._render_class_prompt(
                "config_advice", scenario, mode=mode,
            )
        # "legacy" or unknown — fall back to the agent's default prompt.
        return None

    @staticmethod
    def _render_class_prompt(
        template_name: str,
        scenario: ScenarioMetadata,
        mode: str,
    ) -> str:
        """Render an advisor / config_advice prompt with the same
        substitution rules as the maintainer prompt."""
        import re as _re
        from gpa.eval.prompts import load_prompt

        template = load_prompt(template_name)
        if mode == "with_gla":
            template = template.replace("<!-- WITH_GPA_ONLY -->", "").replace(
                "<!-- END_WITH_GPA_ONLY -->", ""
            )
        else:
            template = _re.sub(
                r"<!-- WITH_GPA_ONLY -->.*?<!-- END_WITH_GPA_ONLY -->\n?",
                "",
                template,
                flags=_re.DOTALL,
            )
        fw = scenario.framework or "the framework"
        return (
            template
            .replace("{framework}", fw)
            .replace("{user_report}", (scenario.bug_description or "").strip())
            .replace(
                "{upstream_snapshot.repo}",
                scenario.upstream_snapshot_repo or "(no snapshot)",
            )
            .replace(
                "{upstream_snapshot.sha}",
                scenario.upstream_snapshot_sha or "HEAD",
            )
        )

    # ------------------------------------------------------------------
    # Scenario-directory helpers (must exclude scenario.md to avoid
    # leaking Ground Truth to the agent)
    # ------------------------------------------------------------------

    _SCENARIO_ALLOWED_EXTS = (".c", ".h", ".glsl", ".vert", ".frag", ".txt")
    _SCENARIO_DENIED_NAMES = frozenset({"scenario.md"})

    def _scenario_root(self, scenario: ScenarioMetadata) -> Optional[Path]:
        sdir = getattr(scenario, "scenario_dir", None)
        return Path(sdir) if sdir else None

    def _is_agent_visible(self, rel: str) -> bool:
        """Policy: agent-visible files are source/shader files only. Never
        scenario.md (Ground Truth lives there). Never hidden dotfiles."""
        name = Path(rel).name
        if name in self._SCENARIO_DENIED_NAMES:
            return False
        if name.startswith("."):
            return False
        return Path(rel).suffix.lower() in self._SCENARIO_ALLOWED_EXTS

    def _list_scenario_files(self, scenario: ScenarioMetadata) -> str:
        root = self._scenario_root(scenario)
        if root is None or not root.exists():
            return "ERROR: scenario directory not available"
        names = []
        for p in sorted(root.iterdir()):
            if p.is_file() and self._is_agent_visible(p.name):
                names.append(p.name)
        return "\n".join(names)

    def _read_scenario_file(self, scenario: ScenarioMetadata, path: str) -> str:
        root = self._scenario_root(scenario)
        if root is None or not root.exists():
            return "ERROR: scenario directory not available"
        try:
            target = (root / path).resolve()
            if not str(target).startswith(str(root.resolve())):
                return f"ERROR: path traversal not allowed: {path!r}"
        except Exception as exc:
            return f"ERROR: invalid path {path!r}: {exc}"
        if not target.exists() or not target.is_file():
            return f"ERROR: file not found: {path!r}"
        rel = str(target.relative_to(root.resolve()))
        if not self._is_agent_visible(rel):
            return f"ERROR: file {path!r} is not agent-visible (scenario.md is withheld to prevent Ground Truth leakage)"
        try:
            return target.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            return f"ERROR: could not read {path!r}: {exc}"

    # ------------------------------------------------------------------
    # Snapshot helpers
    # ------------------------------------------------------------------

    def _ensure_snapshot(self, scenario: ScenarioMetadata) -> Path:
        """Return the working-tree Path for the scenario's upstream snapshot."""
        if self._snapshot_fetcher is None:
            from gpa.eval.snapshot_fetcher import SnapshotFetcher
            self._snapshot_fetcher = SnapshotFetcher()
        from gpa.eval.snapshot_fetcher import SnapshotRef
        ref = SnapshotRef(
            repo_url=scenario.upstream_snapshot_repo,  # type: ignore[arg-type]
            sha=scenario.upstream_snapshot_sha,  # type: ignore[arg-type]
        )
        return self._snapshot_fetcher.fetch(ref)

    def _read_snapshot_file(self, scenario: ScenarioMetadata, path: str) -> str:
        """Read a file from the upstream snapshot and return its contents.

        Returns an "ERROR: ..." string on any failure — never raises.
        Guards against path traversal, missing files, wrong type, fetch
        failures, and files larger than 200 KB (truncated with a marker).
        """
        try:
            root = self._ensure_snapshot(scenario)
        except Exception as exc:
            return f"ERROR: could not fetch upstream snapshot: {exc}"

        try:
            # Resolve the requested path relative to snapshot root;
            # guard against traversal outside root.
            target = (root / path).resolve()
            if not str(target).startswith(str(root.resolve())):
                return f"ERROR: path traversal not allowed: {path!r}"
        except Exception as exc:
            return f"ERROR: invalid path {path!r}: {exc}"

        if not target.exists():
            return f"ERROR: file not found in snapshot: {path!r}"
        if target.is_dir():
            return f"ERROR: {path!r} is a directory, not a file"

        try:
            raw = target.read_bytes()
        except Exception as exc:
            return f"ERROR: could not read {path!r}: {exc}"

        truncated = len(raw) > _SNAPSHOT_MAX_BYTES
        if truncated:
            raw = raw[:_SNAPSHOT_MAX_BYTES]

        try:
            text = raw.decode("utf-8", errors="replace")
        except Exception as exc:
            return f"ERROR: could not decode {path!r} as UTF-8: {exc}"

        if truncated:
            text += f"\n\n[TRUNCATED: file exceeds {_SNAPSHOT_MAX_BYTES // 1024} KB limit]"

        return text

    def _list_snapshot_files(self, scenario: ScenarioMetadata, subdir: str = "") -> str:
        """List entries under subdir in the upstream snapshot.

        Returns a newline-separated list of names with '/' suffix on dirs.
        Returns an "ERROR: ..." string on any failure.
        """
        try:
            root = self._ensure_snapshot(scenario)
        except Exception as exc:
            return f"ERROR: could not fetch upstream snapshot: {exc}"

        try:
            target = (root / subdir).resolve() if subdir else root.resolve()
            if not str(target).startswith(str(root.resolve())):
                return f"ERROR: path traversal not allowed: {subdir!r}"
        except Exception as exc:
            return f"ERROR: invalid path {subdir!r}: {exc}"

        if not target.exists():
            return f"ERROR: directory not found in snapshot: {subdir!r}"
        if not target.is_dir():
            return f"ERROR: {subdir!r} is a file, not a directory"

        try:
            entries = sorted(target.iterdir(), key=lambda p: (p.is_file(), p.name))
            names = [
                (e.name + "/" if e.is_dir() else e.name)
                for e in entries
                if e.name != ".complete"
            ]
        except Exception as exc:
            return f"ERROR: could not list {subdir!r}: {exc}"

        return "\n".join(names)

    def _grep_snapshot(
        self,
        scenario: ScenarioMetadata,
        pattern: str,
        subdir: str = "",
        glob: str = "",
        max_matches: int = 200,
    ) -> str:
        """Grep for `pattern` across files in the upstream snapshot.

        Powered by ripgrep (`rg`) when available; falls back to python
        regex if not. Returns matches in ``path:line:text`` form, capped
        to ``max_matches`` lines. ``glob`` filters by filename (e.g.
        ``"*.ts"``); ``subdir`` narrows the search root.
        """
        import re as _re
        import shutil as _shutil
        import subprocess as _subprocess

        try:
            root = self._ensure_snapshot(scenario)
        except Exception as exc:
            return f"ERROR: could not fetch upstream snapshot: {exc}"

        try:
            search_root = (root / subdir).resolve() if subdir else root.resolve()
            if not str(search_root).startswith(str(root.resolve())):
                return f"ERROR: path traversal not allowed: {subdir!r}"
        except Exception as exc:
            return f"ERROR: invalid subdir {subdir!r}: {exc}"
        if not search_root.exists() or not search_root.is_dir():
            return f"ERROR: {subdir!r} is not a directory in the snapshot"

        rg_path = _shutil.which("rg")
        if rg_path:
            argv = [rg_path, "-n", "--no-heading", "--color", "never",
                    "-m", str(max_matches), pattern]
            if glob:
                argv.extend(["-g", glob])
            argv.append(str(search_root))
            try:
                out = _subprocess.run(
                    argv, capture_output=True, text=True, timeout=20,
                )
            except Exception as exc:
                return f"ERROR: ripgrep invocation failed: {exc}"
            if out.returncode not in (0, 1):  # 1 == no matches
                return f"ERROR: ripgrep: {out.stderr[:300]}"
            lines = out.stdout.splitlines()[:max_matches]
            # Strip the absolute snapshot prefix so paths are snapshot-relative.
            prefix = str(root.resolve()) + "/"
            return "\n".join(
                line[len(prefix):] if line.startswith(prefix) else line
                for line in lines
            ) or "(no matches)"

        # Python fallback — fine for small snapshots, slow for large ones
        try:
            cre = _re.compile(pattern)
        except _re.error as exc:
            return f"ERROR: invalid regex {pattern!r}: {exc}"
        from fnmatch import fnmatch
        matches: list[str] = []
        for p in search_root.rglob("*"):
            if not p.is_file():
                continue
            rel = str(p.relative_to(root))
            if glob and not fnmatch(p.name, glob):
                continue
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            for i, line in enumerate(text.splitlines(), 1):
                if cre.search(line):
                    matches.append(f"{rel}:{i}:{line}")
                    if len(matches) >= max_matches:
                        break
            if len(matches) >= max_matches:
                break
        return "\n".join(matches) or "(no matches)"
