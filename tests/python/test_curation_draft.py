import re
from unittest.mock import MagicMock
from gla.eval.curation.draft import Draft, DraftResult
from gla.eval.curation.llm_client import LLMResponse
from gla.eval.curation.triage import IssueThread, TriageResult

def _fake_response(text: str) -> LLMResponse:
    return LLMResponse(text=text, input_tokens=100, output_tokens=50,
                       cache_creation_input_tokens=0, cache_read_input_tokens=0,
                       stop_reason="end_turn")

_C_CODE = """// SOURCE: https://github.com/x/y/issues/1
#include <GL/gl.h>
int main() { return 0; }
"""

_MD_BODY = """# R1_TEST: Test scenario

## Bug
Something

## Expected Correct Output
Red quad

## Actual Broken Output
Blue quad

## Ground Truth Diagnosis
> "the texture is wrong" (quoted from upstream)

The issue is ...

## Difficulty Rating
3/5

## Adversarial Principles
- Stale state

## How GLA Helps
inspect_drawcall exposes the wrong binding.

## Source
- **URL**: https://github.com/x/y/issues/1
- **Type**: issue
- **Date**: 2024-03-17
- **Commit SHA**: (n/a)
- **Attribution**: Reported by @u

## Tier
core

## API
opengl

## Framework
none

## Bug Signature
```yaml
type: color_histogram_in_region
spec:
  region: [0, 0, 1, 1]
  dominant_color: [1, 0, 0, 1]
  tolerance: 0.1
```

## Predicted GLA Helpfulness
- **Verdict**: yes
- **Reasoning**: inspect_drawcall exposes it.
"""

def test_draft_parses_c_and_md_blocks():
    llm = MagicMock()
    llm.complete.return_value = _fake_response(
        f"```c\n{_C_CODE}```\n\n```markdown\n{_MD_BODY}```"
    )
    d = Draft(llm_client=llm)
    thread = IssueThread(url="https://github.com/x/y/issues/1",
                         title="t", body="b", comments=[])
    triage = TriageResult(verdict="in_scope",
                          fingerprint="state_leak:tex_binding",
                          rejection_reason=None, summary="")

    result = d.draft(thread, triage, scenario_id="r1_test")
    assert "int main()" in result.c_source
    assert "SOURCE: https://github.com/x/y/issues/1" in result.c_source
    assert "## Bug Signature" in result.md_body
    assert result.scenario_id == "r1_test"

def test_draft_rejects_missing_source_comment():
    """C source without // SOURCE: comment should fail validation."""
    llm = MagicMock()
    llm.complete.return_value = _fake_response(
        "```c\nint main(){return 0;}\n```\n\n```markdown\n# x\n```"
    )
    d = Draft(llm_client=llm)
    import pytest
    with pytest.raises(ValueError, match="SOURCE"):
        d.draft(IssueThread(url="https://x/1", title="t", body="b"),
                TriageResult(verdict="in_scope", fingerprint="other:x",
                             rejection_reason=None, summary=""),
                scenario_id="r1_test")

def test_draft_rejects_missing_blockquote_in_diagnosis():
    """Ground Truth Diagnosis without a blockquote (>) fails validation."""
    _c_src_x1 = "// SOURCE: https://x/1\n#include <GL/gl.h>\nint main() { return 0; }\n"
    md_without_quote = _MD_BODY.replace('> "the texture is wrong" (quoted from upstream)\n\n', '')
    llm = MagicMock()
    llm.complete.return_value = _fake_response(
        f"```c\n{_c_src_x1}```\n\n```markdown\n{md_without_quote}```"
    )
    d = Draft(llm_client=llm)
    import pytest
    with pytest.raises(ValueError, match="citation"):
        d.draft(IssueThread(url="https://x/1", title="t", body="b"),
                TriageResult(verdict="in_scope", fingerprint="other:x",
                             rejection_reason=None, summary=""),
                scenario_id="r1_test")

def test_draft_rejects_bug_signature_missing_type():
    """Bug Signature yaml without 'type' key fails validation."""
    md_without_type = _MD_BODY.replace(
        "type: color_histogram_in_region\n", ""
    )
    llm = MagicMock()
    llm.complete.return_value = _fake_response(
        f"```c\n{_C_CODE}```\n\n```markdown\n{md_without_type}```"
    )
    d = Draft(llm_client=llm)
    import pytest
    with pytest.raises(ValueError, match="type"):
        d.draft(IssueThread(url="https://github.com/x/y/issues/1",
                            title="t", body="b"),
                TriageResult(verdict="in_scope",
                             fingerprint="state_leak:x",
                             rejection_reason=None, summary=""),
                scenario_id="r1_test")


def test_draft_rejects_bug_signature_missing_spec():
    """Bug Signature yaml without 'spec' key fails validation."""
    # Replace the full yaml block with one that only has `type` (no spec)
    md_without_spec = re.sub(
        r"```yaml\n.*?\n```",
        "```yaml\ntype: color_histogram_in_region\n```",
        _MD_BODY,
        count=1,
        flags=re.DOTALL,
    )
    assert "spec:" not in md_without_spec
    llm = MagicMock()
    llm.complete.return_value = _fake_response(
        f"```c\n{_C_CODE}```\n\n```markdown\n{md_without_spec}```"
    )
    d = Draft(llm_client=llm)
    import pytest
    with pytest.raises(ValueError, match="spec"):
        d.draft(IssueThread(url="https://github.com/x/y/issues/1",
                            title="t", body="b"),
                TriageResult(verdict="in_scope",
                             fingerprint="state_leak:x",
                             rejection_reason=None, summary=""),
                scenario_id="r1_test")


def test_draft_rejects_malformed_bug_signature_yaml():
    """Bug Signature with broken yaml syntax fails validation."""
    malformed = _MD_BODY.replace(
        "type: color_histogram_in_region\n"
        "spec:\n"
        "  region: [0, 0, 1, 1]\n"
        "  dominant_color: [1, 0, 0, 1]\n"
        "  tolerance: 0.1\n",
        "type: [unclosed\n  spec: {bad}\n",
    )
    llm = MagicMock()
    llm.complete.return_value = _fake_response(
        f"```c\n{_C_CODE}```\n\n```markdown\n{malformed}```"
    )
    d = Draft(llm_client=llm)
    import pytest
    with pytest.raises(ValueError):
        d.draft(IssueThread(url="https://github.com/x/y/issues/1",
                            title="t", body="b"),
                TriageResult(verdict="in_scope",
                             fingerprint="state_leak:x",
                             rejection_reason=None, summary=""),
                scenario_id="r1_test")


def test_draft_preserves_nested_yaml_fence_in_md():
    """Markdown block containing a yaml fenced block must not be truncated."""
    llm = MagicMock()
    llm.complete.return_value = _fake_response(
        f"```c\n{_C_CODE}```\n\n```markdown\n{_MD_BODY}```"
    )
    d = Draft(llm_client=llm)
    result = d.draft(
        IssueThread(url="https://github.com/x/y/issues/1",
                    title="t", body="b", comments=[]),
        TriageResult(verdict="in_scope", fingerprint="state_leak:x",
                     rejection_reason=None, summary=""),
        scenario_id="r1_test",
    )
    # These assertions are for sections that appear AFTER the yaml block
    assert "## Predicted GLA Helpfulness" in result.md_body
    assert "inspect_drawcall exposes it" in result.md_body
