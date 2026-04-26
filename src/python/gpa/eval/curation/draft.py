from __future__ import annotations
import re
from typing import Optional

import yaml

from gpa.eval.curation.llm_client import LLMClient
from gpa.eval.curation.prompts import load_prompt
from gpa.eval.curation.triage import IssueThread, TriageResult


_FILENAME_MARKER_RE = re.compile(r"<!--\s*filename:\s*([^\s]+)\s*-->", re.IGNORECASE)
# Explicit drafter-rejection marker. The drafter prompt instructs the LLM to
# emit this as a top-level HTML comment when a candidate fundamentally cannot
# be drafted (not portable to C, not portable to snapshot, etc.). The reason
# is a slug like `not_portable_to_c_or_snapshot` or `not_a_rendering_bug`.
_DRAFT_ERROR_MARKER_RE = re.compile(
    r"<!--\s*draft_error:\s*([a-z0-9_]+)\s*-->", re.IGNORECASE
)
# Opening fence: ```<lang>\n at the start of a line.
_FENCE_OPEN_RE = re.compile(r"^```([a-zA-Z0-9_+-]*)\s*$", re.MULTILINE)
# Closing fence: ``` (bare) at the start of a line.
_FENCE_CLOSE_RE = re.compile(r"^```\s*$", re.MULTILINE)

_ALLOWED_EXTENSIONS = {".c", ".h", ".md", ".glsl", ".vert", ".frag"}


class DraftRejectedByModel(ValueError):
    """The drafter LLM explicitly declined to draft a scenario.

    Raised when the LLM emits a `<!-- draft_error: <reason> -->` marker (per the
    drafter prompt's principled-rejection convention). This is distinct from a
    format failure: retrying the LLM will not produce a different answer, and
    the upstream pipeline can route these to a separate bucket from
    'draft_invalid' when reporting yield.

    The `reason` attribute holds the slug from the marker (e.g.,
    `not_portable_to_c_or_snapshot`).
    """

    def __init__(self, reason: str, message: str = ""):
        self.reason = reason
        super().__init__(message or f"drafter declined: {reason}")


class DraftResult:
    """Result of the Draft stage.

    The drafter can emit multiple files per scenario (main.c, scenario.md, plus
    optional additional C/header/shader sources or verbatim upstream snapshots).

    The primary field is ``files``: a mapping from filename (relative to the
    scenario directory) to file contents.

    Backward-compatible ``c_source`` / ``md_body`` properties are kept for
    callers that have not yet migrated (Validator, commit_scenario, cached
    pipeline outputs).  ``DraftResult(c_source=..., md_body=...)`` still works
    and is internally normalized to ``files``.
    """

    __slots__ = ("scenario_id", "files")

    def __init__(
        self,
        scenario_id: str,
        files: Optional[dict] = None,
        *,
        c_source: Optional[str] = None,
        md_body: Optional[str] = None,
    ) -> None:
        if files is None:
            files = {}
            if c_source is not None:
                files["main.c"] = c_source
            if md_body is not None:
                files["scenario.md"] = md_body
        else:
            # Disallow passing both positional files and legacy kwargs.
            if c_source is not None or md_body is not None:
                raise TypeError(
                    "DraftResult: pass either files=... or "
                    "c_source=/md_body=, not both"
                )
            files = dict(files)
        self.scenario_id = scenario_id
        self.files = files

    # --- primary accessors ---

    @property
    def main_c(self) -> str:
        """Primary C source. Returns files['main.c'] or the first .c file."""
        if "main.c" in self.files:
            return self.files["main.c"]
        for name in sorted(self.files):
            if name.endswith(".c"):
                return self.files[name]
        return ""

    @property
    def scenario_md(self) -> str:
        """Scenario markdown body."""
        return self.files.get("scenario.md", "")

    # --- backward-compat aliases ---

    @property
    def c_source(self) -> str:
        return self.main_c

    @property
    def md_body(self) -> str:
        return self.scenario_md

    # Equality / repr for debugging and test ergonomics.
    def __eq__(self, other: object) -> bool:
        if not isinstance(other, DraftResult):
            return NotImplemented
        return self.scenario_id == other.scenario_id and self.files == other.files

    def __repr__(self) -> str:
        return (
            f"DraftResult(scenario_id={self.scenario_id!r}, "
            f"files={{{', '.join(repr(k) for k in self.files)}}})"
        )


class Draft:
    def __init__(self, llm_client: LLMClient):
        self._llm = llm_client
        self._system = load_prompt("draft_core_system")

    def draft(self, thread: IssueThread, triage: TriageResult,
              scenario_id: str,
              previous_error: Optional[str] = None) -> DraftResult:
        """Generate a scenario draft.

        If ``previous_error`` is provided, it's included in the user message as
        feedback from a failed prior attempt. The drafter should address the
        specific issue and produce a valid draft on retry.
        """
        base_user = (
            f"Scenario ID: {scenario_id}\n"
            f"Triage fingerprint: {triage.fingerprint}\n"
            f"Triage summary: {triage.summary}\n\n"
            f"URL: {thread.url}\n"
            f"Title: {thread.title}\n\n"
            f"Body:\n{thread.body}\n\n"
            + "\n".join(f"Comment {i+1}:\n{c}" for i, c in enumerate(thread.comments))
        )

        if previous_error:
            user = (
                base_user
                + "\n\n---\n\n"
                + "IMPORTANT: Your previous draft attempt was rejected by validation with this error:\n\n"
                + f"    {previous_error}\n\n"
                + "Please produce a new draft that fixes this specific issue. All other rules still apply."
            )
        else:
            user = base_user

        resp = self._llm.complete(
            system=self._system,
            messages=[{"role": "user", "content": user}],
            max_tokens=8000,
        )

        files = self._parse_files(resp.text)
        self._validate(files, thread.url)
        return DraftResult(scenario_id=scenario_id, files=files)

    @staticmethod
    def _parse_files(text: str) -> dict:
        """Parse LLM response into {filename: content}.

        Expected format: each fenced block is preceded by a
        ``<!-- filename: X -->`` HTML comment marker.  Blocks without a
        preceding filename marker are ignored.

        Raises:
          DraftRejectedByModel: if the LLM emitted a
            ``<!-- draft_error: <reason> -->`` marker AND no filename-marked
            blocks (principled refusal per drafter prompt).
          ValueError: if
            - No filename-marked blocks AND no draft_error marker are found
            - A filename uses an absolute path or contains ``..``
            - A filename has an extension outside the allowed set
            - Duplicate filenames are emitted
            - ``main.c`` (or any ``.c`` file) or ``scenario.md`` is missing
        """
        # Find every filename marker and its position.
        markers = [
            (m.start(), m.end(), m.group(1).strip())
            for m in _FILENAME_MARKER_RE.finditer(text)
        ]
        out: dict = {}
        for i, (start, end, filename) in enumerate(markers):
            # The block for this marker is bounded by the next marker (or EOF).
            segment_end = markers[i + 1][0] if i + 1 < len(markers) else len(text)
            segment = text[end:segment_end]

            # Find the opening fence within the segment.
            m_open = _FENCE_OPEN_RE.search(segment)
            if not m_open:
                raise ValueError(
                    f"filename marker '{filename}' has no following fenced block"
                )

            # The closing fence is the LAST bare ``` line in the segment.  This
            # lets a file's body contain nested fences (e.g. scenario.md
            # contains a ```yaml ... ``` block inside its ```markdown fence).
            body_start = m_open.end() + 1  # skip the newline after the opener
            closes = list(_FENCE_CLOSE_RE.finditer(segment, m_open.end()))
            if not closes:
                raise ValueError(
                    f"filename marker '{filename}' block has no closing fence"
                )
            m_close = closes[-1]
            body = segment[body_start:m_close.start()]
            # Drop trailing newline before the closing fence, if any, to match
            # how the LLM will naturally format output.
            if body.endswith("\n"):
                body = body[:-1]

            # Validate filename.
            if filename.startswith("/"):
                raise ValueError(
                    f"filename '{filename}' is absolute (starts with '/')"
                )
            parts = filename.split("/")
            if ".." in parts:
                raise ValueError(
                    f"filename '{filename}' traverses parents ('..' component)"
                )
            if any(not p for p in parts):
                raise ValueError(
                    f"filename '{filename}' has an empty path component"
                )
            basename = parts[-1]
            if "." not in basename:
                raise ValueError(f"filename '{filename}' has no extension")
            ext = "." + basename.rsplit(".", 1)[1].lower()
            if ext not in _ALLOWED_EXTENSIONS:
                raise ValueError(
                    f"filename '{filename}' extension '{ext}' not allowed; "
                    f"allowed: {sorted(_ALLOWED_EXTENSIONS)}"
                )
            if filename in out:
                raise ValueError(f"duplicate filename '{filename}'")

            out[filename] = body

        if not out:
            # If the LLM emitted an explicit principled-rejection marker,
            # surface it as DraftRejectedByModel so callers can route it to
            # a separate bucket from format failures (and skip the retry,
            # which won't change the model's mind).
            err_match = _DRAFT_ERROR_MARKER_RE.search(text)
            if err_match:
                raise DraftRejectedByModel(
                    reason=err_match.group(1).strip().lower(),
                    message=(
                        f"drafter declined: <!-- draft_error: "
                        f"{err_match.group(1).strip()} -->"
                    ),
                )
            raise ValueError(
                "No filename-marked fenced blocks found. "
                "Expected: <!-- filename: <path> -->\n```<lang>\n...\n```"
            )
        if "main.c" not in out and not any(n.endswith(".c") for n in out):
            raise ValueError("no .c source file in draft output")
        if "scenario.md" not in out:
            raise ValueError("scenario.md missing from draft output")
        return out

    @staticmethod
    def _validate(files: dict, issue_url: str) -> None:
        # At least one .c file must be present, with a SOURCE comment matching
        # the issue URL on the primary source.
        c_sources = {n: content for n, content in files.items() if n.endswith(".c")}
        if not c_sources:
            raise ValueError("no .c source file present")

        primary = files.get("main.c") or c_sources[sorted(c_sources)[0]]
        if "// SOURCE:" not in primary:
            raise ValueError("primary C source missing // SOURCE: <url> comment")
        if issue_url not in primary:
            raise ValueError("primary C source // SOURCE: does not match issue URL")

        md_body = files.get("scenario.md", "")
        if not md_body:
            raise ValueError("scenario.md missing")

        # Ground Truth section must exist (accepts both the new
        # `## Ground Truth` heading and the legacy `## Ground Truth Diagnosis`)
        m = re.search(
            r"##\s+Ground Truth(?:\s+Diagnosis)?\s*\n(.+?)(?=\n##\s+|\Z)",
            md_body, re.DOTALL | re.IGNORECASE,
        )
        if not m:
            raise ValueError("Ground Truth section missing")
        diagnosis_body = m.group(1)

        # Diagnosis must cite upstream via ONE of:
        #   (a) Blockquote (> ...): verbatim quote from issue/PR/commit
        #   (b) PR reference (PR #NNN, pull request #NNN)
        #   (c) Commit reference (commit <hex>, (abc1234), or bare <hex>{7,}
        #       near "commit"/"PR")
        #   (d) GitHub URL to pull/commit
        has_blockquote = bool(re.search(r"^>\s+", diagnosis_body, re.MULTILINE))
        has_pr_ref = bool(re.search(
            r"\b(?:PR|pull\s+request|pull/)\s*#?(\d+)\b",
            diagnosis_body, re.IGNORECASE,
        ))
        has_commit_ref = bool(re.search(
            r"\b(?:commit\s+|/commit/)([a-f0-9]{7,})\b",
            diagnosis_body, re.IGNORECASE,
        ))
        has_github_url = bool(re.search(
            r"github\.com/[\w.-]+/[\w.-]+/(?:pull|commit)/[\w]+",
            diagnosis_body, re.IGNORECASE,
        ))

        if not (has_blockquote or has_pr_ref or has_commit_ref or has_github_url):
            raise ValueError(
                "Ground Truth Diagnosis missing upstream citation. "
                "Cite via (a) a > blockquote, (b) 'PR #NNN' / 'pull request #NNN', "
                "(c) 'commit <sha>' where sha is 7+ hex chars, or "
                "(d) a github.com/.../pull|commit/... URL."
            )
        # Bug Signature must be a well-formed yaml dict with 'type' and 'spec'
        m_sig = re.search(
            r"##\s+Bug Signature\s*\n.*?```yaml\s*\n(.+?)\n```",
            md_body, re.DOTALL | re.IGNORECASE)
        if not m_sig:
            raise ValueError("Bug Signature section missing or YAML block absent")
        try:
            parsed = yaml.safe_load(m_sig.group(1))
        except yaml.YAMLError as e:
            raise ValueError(f"Bug Signature YAML parse failed: {e}")
        if not isinstance(parsed, dict) or "type" not in parsed or "spec" not in parsed:
            raise ValueError("Bug Signature must have 'type' and 'spec' keys")

        # Defense-in-depth path sanity check (also enforced in _parse_files).
        for filename in files:
            parts = filename.split("/")
            if ".." in parts or filename.startswith("/"):
                raise ValueError(f"invalid path '{filename}'")
