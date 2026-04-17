from __future__ import annotations
import base64
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from gla.eval.curation.draft import DraftResult
from gla.eval.curation.prompts import load_prompt
from gla.eval.curation.signature_matchers import match_signature
from gla.eval.scenario import ScenarioLoader


@dataclass
class ValidationResult:
    ok: bool
    reason: str
    framebuffer_png: Optional[bytes] = None
    metadata: Optional[dict] = None


class Validator:
    """Builds, runs, and validates a drafted scenario."""

    def __init__(self, eval_dir: Path | str, runner: Any, llm_fallback: Any = None):
        self.eval_dir = Path(eval_dir)
        self.eval_dir.mkdir(parents=True, exist_ok=True)
        self._runner = runner  # must expose build_and_capture(scenario_id) -> dict
        self._llm_fallback = llm_fallback

    def validate(self, draft: DraftResult) -> ValidationResult:
        # 1. Write artifacts into eval dir
        c_path = self.eval_dir / f"{draft.scenario_id}.c"
        md_path = self.eval_dir / f"{draft.scenario_id}.md"
        c_path.write_text(draft.c_source)
        md_path.write_text(draft.md_body)

        # 2. Parse the md for the signature
        try:
            scenario = ScenarioLoader(eval_dir=str(self.eval_dir)).load(draft.scenario_id)
        except Exception as e:
            return ValidationResult(ok=False, reason=f"scenario parse failed: {e}")
        if not scenario.bug_signature:
            return ValidationResult(ok=False, reason="scenario missing Bug Signature")

        # 3. Build and run
        try:
            capture = self._runner.build_and_capture(draft.scenario_id)
        except Exception as e:
            return ValidationResult(ok=False, reason=f"build/run failed: {e}")

        fb = capture.get("framebuffer_png")
        meta = capture.get("metadata") or {}
        if not fb:
            return ValidationResult(ok=False, reason="no framebuffer captured")

        # 4. Signature match
        m = match_signature(fb, scenario.bug_signature, metadata=meta)
        if m.matched:
            return ValidationResult(ok=True, reason="signature matched",
                                    framebuffer_png=fb, metadata=meta)
        if m.ambiguous and self._llm_fallback:
            judge = self._ask_llm(draft.md_body, fb)
            if judge:
                return ValidationResult(
                    ok=True,
                    reason="LLM fallback confirmed match",
                    framebuffer_png=fb, metadata=meta,
                )
            return ValidationResult(
                ok=False,
                reason="LLM fallback rejected match",
                framebuffer_png=fb, metadata=meta,
            )
        if m.ambiguous:
            return ValidationResult(ok=False,
                reason=f"signature ambiguous (no fallback): {m.reason}",
                framebuffer_png=fb, metadata=meta)
        return ValidationResult(ok=False, reason=f"signature did not match: {m.reason}",
                                framebuffer_png=fb, metadata=meta)

    def _ask_llm(self, md_body: str, fb_png: bytes) -> bool:
        sys = load_prompt("symptom_match_fallback_system")
        b64 = base64.b64encode(fb_png).decode()
        content = [
            {"type": "text", "text": f"Scenario:\n{md_body}"},
            {"type": "image", "source": {"type": "base64",
                "media_type": "image/png", "data": b64}},
        ]
        resp = self._llm_fallback.complete(
            system=sys,
            messages=[{"role": "user", "content": content}])
        m = re.search(r"```json\s*\n(.+?)\n```", resp.text, re.DOTALL)
        raw = m.group(1) if m else resp.text
        try:
            return bool(json.loads(raw).get("matches"))
        except (json.JSONDecodeError, AttributeError):
            return False
