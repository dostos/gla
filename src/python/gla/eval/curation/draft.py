from __future__ import annotations
import re
from dataclasses import dataclass

import yaml

from gla.eval.curation.llm_client import LLMClient
from gla.eval.curation.prompts import load_prompt
from gla.eval.curation.triage import IssueThread, TriageResult


@dataclass
class DraftResult:
    scenario_id: str
    c_source: str
    md_body: str


class Draft:
    def __init__(self, llm_client: LLMClient):
        self._llm = llm_client
        self._system = load_prompt("draft_core_system")

    def draft(self, thread: IssueThread, triage: TriageResult,
              scenario_id: str) -> DraftResult:
        user = (
            f"Scenario ID: {scenario_id}\n"
            f"Triage fingerprint: {triage.fingerprint}\n"
            f"Triage summary: {triage.summary}\n\n"
            f"URL: {thread.url}\n"
            f"Title: {thread.title}\n\n"
            f"Body:\n{thread.body}\n\n"
            + "\n".join(f"Comment {i+1}:\n{c}" for i, c in enumerate(thread.comments))
        )
        resp = self._llm.complete(
            system=self._system,
            messages=[{"role": "user", "content": user}],
            max_tokens=8000,
        )

        c_src, md_body = self._parse_blocks(resp.text)
        self._validate(c_src, md_body, thread.url)
        return DraftResult(scenario_id=scenario_id, c_source=c_src, md_body=md_body)

    @staticmethod
    def _parse_blocks(text: str) -> tuple[str, str]:
        m_c = re.search(r"```c\s*\n(.+?)\n```", text, re.DOTALL)
        m_md = re.search(r"```markdown\s*\n(.+)\n```\s*$", text, re.DOTALL)
        if not m_c or not m_md:
            raise ValueError("Draft response missing required c or markdown block")
        return m_c.group(1), m_md.group(1)

    @staticmethod
    def _validate(c_src: str, md_body: str, issue_url: str) -> None:
        if "// SOURCE:" not in c_src:
            raise ValueError("C source missing // SOURCE: <url> comment")
        if issue_url not in c_src:
            raise ValueError("C source // SOURCE: does not match issue URL")
        # Ground Truth Diagnosis must contain a blockquote citation
        m = re.search(r"##\s+Ground Truth Diagnosis\s*\n(.+?)(?=\n##\s+|\Z)",
                      md_body, re.DOTALL | re.IGNORECASE)
        if not m:
            raise ValueError("Ground Truth Diagnosis section missing")
        if not re.search(r"^>\s+", m.group(1), re.MULTILINE):
            raise ValueError("Ground Truth Diagnosis missing upstream citation (>) blockquote")
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
