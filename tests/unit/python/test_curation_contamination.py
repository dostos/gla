"""Unit tests for the validator's contamination checker.

A contaminated scenario leaks its diagnosis to the eval agent — either via
hint comments in source files, via runtime-output strings that announce
the bug, or via a scenario.md `## User Report` section that states the
root cause instead of describing symptoms.
"""
from pathlib import Path

import pytest

from gpa.eval.curation.validate import check_contamination


GOOD_MAIN_C = """\
// SOURCE: https://github.com/example/repo/issues/1
#include <GL/gl.h>

int main(void) {
    glClearColor(1.0f, 0.0f, 0.0f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT);
    return 0;
}
"""

GOOD_SCENARIO_MD = """\
# E1: Example

## User Report
Two quads render on screen — the left one should be red, the right one blue.
Both come out red instead. No console errors. Textures were uploaded and
both IDs are valid (queried as RGBA8 512x512).

## Expected Correct Output
Left quad red, right quad blue.

## Actual Broken Output
Both quads are red.

## Ground Truth
The second `glBindTexture(GL_TEXTURE_2D, tex_blue)` call is omitted before
drawing the right quad, so the right draw inherits the red texture from
the previous draw.

## Difficulty Rating
2/5

## Adversarial Principles
- state-leak-from-previous-draw

## How OpenGPA Helps
`inspect_drawcall(aspect=textures)` reveals the identical texture_id bound
for both draws.

## Tier
core

## API
opengl

## Framework
none

## Bug Signature
```yaml
type: framebuffer_dominant_color
spec:
  expected_rgba: [1.0, 0.0, 0.0, 1.0]
  tolerance: 0.1
```
"""


def _write_scenario(tmp_path: Path, main_c: str, scenario_md: str) -> Path:
    d = tmp_path / "e1_example"
    d.mkdir()
    (d / "main.c").write_text(main_c)
    (d / "scenario.md").write_text(scenario_md)
    return d


def test_clean_scenario_passes(tmp_path):
    d = _write_scenario(tmp_path, GOOD_MAIN_C, GOOD_SCENARIO_MD)
    assert check_contamination(d) is None


def test_bug_comment_in_source_rejected(tmp_path):
    dirty = GOOD_MAIN_C.replace(
        "glClearColor(1.0f, 0.0f, 0.0f, 1.0f);",
        "// BUG: should be blue, not red\n    glClearColor(1.0f, 0.0f, 0.0f, 1.0f);",
    )
    d = _write_scenario(tmp_path, dirty, GOOD_SCENARIO_MD)
    reason = check_contamination(d)
    assert reason is not None
    assert "BUG" in reason


def test_intentionally_omitted_comment_rejected(tmp_path):
    dirty = GOOD_MAIN_C.replace(
        "int main(void) {",
        "int main(void) {\n    // intentionally omitted: glEnable(GL_DEPTH_TEST);",
    )
    d = _write_scenario(tmp_path, dirty, GOOD_SCENARIO_MD)
    assert "intentionally" in (check_contamination(d) or "")


def test_arrow_missing_comment_rejected(tmp_path):
    dirty = GOOD_MAIN_C.replace(
        "glClear(GL_COLOR_BUFFER_BIT);",
        "glClear(GL_COLOR_BUFFER_BIT);  // <-- MISSING depth clear here",
    )
    d = _write_scenario(tmp_path, dirty, GOOD_SCENARIO_MD)
    assert "MISSING" in (check_contamination(d) or "")


def test_runtime_verdict_printf_rejected(tmp_path):
    dirty = GOOD_MAIN_C.replace(
        "return 0;",
        'printf("verdict: %s\\n", ok ? "clean" : "bug reproduced");\n    return 0;',
    )
    d = _write_scenario(tmp_path, dirty, GOOD_SCENARIO_MD)
    reason = check_contamination(d)
    assert reason is not None
    assert "runtime-output leak" in reason or "verdict" in reason


def test_shader_file_hint_rejected(tmp_path):
    d = _write_scenario(tmp_path, GOOD_MAIN_C, GOOD_SCENARIO_MD)
    (d / "frag.glsl").write_text(
        "#version 330\n"
        "// BUG: alpha is hardcoded to 1.0 — should be the sample alpha\n"
        "void main() { gl_FragColor = vec4(1,0,0,1); }\n"
    )
    assert "BUG" in (check_contamination(d) or "")


def test_missing_user_report_section_rejected(tmp_path):
    no_user_report = GOOD_SCENARIO_MD.replace("## User Report\n", "## Bug\n")
    d = _write_scenario(tmp_path, GOOD_MAIN_C, no_user_report)
    assert "User Report" in (check_contamination(d) or "")


def test_missing_ground_truth_section_rejected(tmp_path):
    no_gt = GOOD_SCENARIO_MD.replace(
        "## Ground Truth\n", "## Ground Truth Diagnosis\n"
    )
    d = _write_scenario(tmp_path, GOOD_MAIN_C, no_gt)
    assert "Ground Truth" in (check_contamination(d) or "")


def test_user_report_may_carry_reporter_hypothesis(tmp_path):
    """Real GitHub issue reporters often guess the cause in their own words.
    That is NOT contamination — the agent sees what a real debugger would.
    """
    reporter_guess = GOOD_SCENARIO_MD.replace(
        "Both come out red instead.",
        "Both come out red instead. I think the bug is a missing bind, "
        "but not sure.",
    )
    d = _write_scenario(tmp_path, GOOD_MAIN_C, reporter_guess)
    assert check_contamination(d) is None


def test_neutral_what_comments_are_allowed(tmp_path):
    ok = GOOD_MAIN_C.replace(
        "glClear(GL_COLOR_BUFFER_BIT);",
        "// upload vertex data for the quad\n    glClear(GL_COLOR_BUFFER_BIT);",
    )
    d = _write_scenario(tmp_path, ok, GOOD_SCENARIO_MD)
    assert check_contamination(d) is None
