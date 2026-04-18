from unittest.mock import MagicMock
from pathlib import Path
from gla.eval.curation.validate import Validator, ValidationResult
from gla.eval.curation.draft import DraftResult
from gla.eval.curation.llm_client import LLMResponse

def test_validator_builds_runs_and_signature_matches(tmp_path):
    scenario_id = "r_test_ok"
    draft = DraftResult(
        scenario_id=scenario_id,
        c_source="// SOURCE: https://x/1\nint main(){return 0;}",
        md_body=(
            "# R_TEST_OK\n"
            "## Bug\nb\n"
            "## Expected Correct Output\ne\n"
            "## Actual Broken Output\na\n"
            "## Ground Truth Diagnosis\n> quote\ndiag\n"
            "## Difficulty Rating\n3/5\n"
            "## Adversarial Principles\n- p\n"
            "## How GLA Helps\nh\n"
            "## Source\n- **URL**: https://x/1\n"
            "## Tier\ncore\n"
            "## API\nopengl\n"
            "## Framework\nnone\n"
            "## Bug Signature\n```yaml\n"
            "type: framebuffer_dominant_color\n"
            "spec:\n  color: [1.0, 0.0, 0.0, 1.0]\n  tolerance: 0.1\n"
            "```\n"
            "## Predicted GLA Helpfulness\n- **Verdict**: yes\n"
            "- **Reasoning**: x\n"
        ),
    )

    fake_runner = MagicMock()
    # fake framebuffer bytes — a red 64x64 PNG (read from fixture)
    red_png = Path(__file__).parent.joinpath(
        "fixtures/curation/framebuffers/solid_red.png").read_bytes()
    fake_runner.build_and_capture.return_value = {
        "framebuffer_png": red_png,
        "metadata": {"draw_call_count": 1, "draw_calls": []},
    }

    v = Validator(eval_dir=tmp_path, runner=fake_runner)
    result = v.validate(draft)

    assert result.ok is True
    assert result.reason == "signature matched"
    # The C source and md were written to the scenario directory
    assert (tmp_path / "r_test_ok" / "main.c").exists()
    assert (tmp_path / "r_test_ok" / "scenario.md").exists()

def test_validator_fails_on_signature_mismatch(tmp_path):
    """Validator returns ok=False when captured frame doesn't match the signature."""
    scenario_id = "r_test_mismatch"
    draft = DraftResult(
        scenario_id=scenario_id,
        c_source="// SOURCE: https://x/1\nint main(){return 0;}",
        md_body=(
            "# R_TEST_MISMATCH\n"
            "## Bug\nb\n## Expected Correct Output\ne\n## Actual Broken Output\na\n"
            "## Ground Truth Diagnosis\n> quote\ndiag\n## Difficulty Rating\n3/5\n"
            "## Adversarial Principles\n- p\n## How GLA Helps\nh\n"
            "## Source\n- **URL**: https://x/1\n## Tier\ncore\n## API\nopengl\n"
            "## Framework\nnone\n"
            "## Bug Signature\n```yaml\n"
            "type: framebuffer_dominant_color\n"
            "spec:\n  color: [1.0, 0.0, 0.0, 1.0]\n  tolerance: 0.1\n"
            "```\n"
            "## Predicted GLA Helpfulness\n- **Verdict**: yes\n- **Reasoning**: x\n"
        ),
    )

    fake_runner = MagicMock()
    # Return a BLUE framebuffer but signature expects RED
    blue_png = Path(__file__).parent.joinpath(
        "fixtures/curation/framebuffers/solid_blue.png").read_bytes()
    fake_runner.build_and_capture.return_value = {
        "framebuffer_png": blue_png,
        "metadata": {"draw_call_count": 1, "draw_calls": []},
    }

    v = Validator(eval_dir=tmp_path, runner=fake_runner)
    result = v.validate(draft)
    assert result.ok is False
    assert "did not match" in result.reason


def test_validator_cleans_up_on_mismatch(tmp_path):
    """On ok=False the .c and .md files must be removed from eval_dir."""
    scenario_id = "r_test_cleanup"
    draft = DraftResult(
        scenario_id=scenario_id,
        c_source="// SOURCE: https://x/1\nint main(){return 0;}",
        md_body=(
            "# R_TEST_CLEANUP\n"
            "## Bug\nb\n## Expected Correct Output\ne\n## Actual Broken Output\na\n"
            "## Ground Truth Diagnosis\n> quote\ndiag\n## Difficulty Rating\n3/5\n"
            "## Adversarial Principles\n- p\n## How GLA Helps\nh\n"
            "## Source\n- **URL**: https://x/1\n## Tier\ncore\n## API\nopengl\n"
            "## Framework\nnone\n"
            "## Bug Signature\n```yaml\n"
            "type: framebuffer_dominant_color\n"
            "spec:\n  color: [1.0, 0.0, 0.0, 1.0]\n  tolerance: 0.1\n"
            "```\n"
            "## Predicted GLA Helpfulness\n- **Verdict**: yes\n- **Reasoning**: x\n"
        ),
    )
    fake_runner = MagicMock()
    # Blue where signature wants red → mismatch
    blue_png = Path(__file__).parent.joinpath(
        "fixtures/curation/framebuffers/solid_blue.png").read_bytes()
    fake_runner.build_and_capture.return_value = {
        "framebuffer_png": blue_png,
        "metadata": {"draw_call_count": 1, "draw_calls": []},
    }
    v = Validator(eval_dir=tmp_path, runner=fake_runner)
    result = v.validate(draft)
    assert result.ok is False
    assert not (tmp_path / scenario_id / "main.c").exists()
    assert not (tmp_path / scenario_id / "scenario.md").exists()


def test_validator_cleans_up_when_build_fails(tmp_path):
    """Even if build/run raises, the files should still be cleaned up."""
    scenario_id = "r_test_build_fail"
    draft = DraftResult(
        scenario_id=scenario_id,
        c_source="// SOURCE: https://x/1\nint main(){return 0;}",
        md_body=(
            "# R_TEST_BUILD_FAIL\n"
            "## Bug\nb\n## Expected Correct Output\ne\n## Actual Broken Output\na\n"
            "## Ground Truth Diagnosis\n> quote\ndiag\n## Difficulty Rating\n3/5\n"
            "## Adversarial Principles\n- p\n## How GLA Helps\nh\n"
            "## Source\n- **URL**: https://x/1\n## Tier\ncore\n## API\nopengl\n"
            "## Framework\nnone\n"
            "## Bug Signature\n```yaml\n"
            "type: framebuffer_dominant_color\n"
            "spec:\n  color: [1.0, 0.0, 0.0, 1.0]\n  tolerance: 0.1\n"
            "```\n"
            "## Predicted GLA Helpfulness\n- **Verdict**: yes\n- **Reasoning**: x\n"
        ),
    )
    fake_runner = MagicMock()
    fake_runner.build_and_capture.side_effect = RuntimeError("bazel broke")
    v = Validator(eval_dir=tmp_path, runner=fake_runner)
    result = v.validate(draft)
    assert result.ok is False
    assert "build/run failed" in result.reason
    assert not (tmp_path / scenario_id / "main.c").exists()
    assert not (tmp_path / scenario_id / "scenario.md").exists()


def test_validator_keeps_files_on_success(tmp_path):
    """Sanity check: on ok=True the files must remain (they are committed later)."""
    scenario_id = "r_test_ok_keep"
    draft = DraftResult(
        scenario_id=scenario_id,
        c_source="// SOURCE: https://x/1\nint main(){return 0;}",
        md_body=(
            "# R_TEST_OK_KEEP\n"
            "## Bug\nb\n## Expected Correct Output\ne\n## Actual Broken Output\na\n"
            "## Ground Truth Diagnosis\n> quote\ndiag\n## Difficulty Rating\n3/5\n"
            "## Adversarial Principles\n- p\n## How GLA Helps\nh\n"
            "## Source\n- **URL**: https://x/1\n## Tier\ncore\n## API\nopengl\n"
            "## Framework\nnone\n"
            "## Bug Signature\n```yaml\n"
            "type: framebuffer_dominant_color\n"
            "spec:\n  color: [1.0, 0.0, 0.0, 1.0]\n  tolerance: 0.1\n"
            "```\n"
            "## Predicted GLA Helpfulness\n- **Verdict**: yes\n- **Reasoning**: x\n"
        ),
    )
    red_png = Path(__file__).parent.joinpath(
        "fixtures/curation/framebuffers/solid_red.png").read_bytes()
    fake_runner = MagicMock()
    fake_runner.build_and_capture.return_value = {
        "framebuffer_png": red_png,
        "metadata": {"draw_call_count": 1, "draw_calls": []},
    }
    v = Validator(eval_dir=tmp_path, runner=fake_runner)
    result = v.validate(draft)
    assert result.ok is True
    assert (tmp_path / scenario_id / "main.c").exists()
    assert (tmp_path / scenario_id / "scenario.md").exists()


def test_validator_writes_multiple_files_to_scenario_dir(tmp_path):
    """Validator writes all files from DraftResult.files, not just main.c + scenario.md."""
    scenario_id = "r_multi"
    draft = DraftResult(
        scenario_id=scenario_id,
        files={
            "main.c": "// SOURCE: https://x/1\nint main(){return 0;}",
            "helper.c": "void helper(void) {}",
            "scenario.md": (
                "# R_MULTI\n"
                "## Bug\nb\n## Expected Correct Output\ne\n"
                "## Actual Broken Output\na\n"
                "## Ground Truth Diagnosis\n> quote\ndiag\n"
                "## Difficulty Rating\n3/5\n"
                "## Adversarial Principles\n- p\n"
                "## How GLA Helps\nh\n## Source\n- **URL**: https://x/1\n"
                "## Tier\ncore\n## API\nopengl\n## Framework\nnone\n"
                "## Bug Signature\n```yaml\n"
                "type: framebuffer_dominant_color\n"
                "spec:\n  color: [1.0, 0.0, 0.0, 1.0]\n  tolerance: 0.1\n"
                "```\n"
                "## Predicted GLA Helpfulness\n- **Verdict**: yes\n"
                "- **Reasoning**: x\n"
            ),
        },
    )

    fake_runner = MagicMock()
    red_png = Path(__file__).parent.joinpath(
        "fixtures/curation/framebuffers/solid_red.png").read_bytes()
    fake_runner.build_and_capture.return_value = {
        "framebuffer_png": red_png,
        "metadata": {"draw_call_count": 1, "draw_calls": []},
    }

    v = Validator(eval_dir=tmp_path, runner=fake_runner)
    result = v.validate(draft)

    assert result.ok is True
    scenario_dir = tmp_path / scenario_id
    assert (scenario_dir / "main.c").exists()
    assert (scenario_dir / "helper.c").exists()
    assert (scenario_dir / "scenario.md").exists()


def test_validator_cleans_up_whole_dir_on_failure(tmp_path):
    """When validation fails, the entire scenario dir (including extra files) is removed."""
    draft = DraftResult(
        scenario_id="r_fail",
        files={
            "main.c": "// SOURCE: https://x/1\nint main(){return 0;}",
            "helper.c": "void helper(void) {}",
            "scenario.md": (
                "# R_FAIL\n## Bug\nb\n## Expected Correct Output\ne\n"
                "## Actual Broken Output\na\n## Ground Truth Diagnosis\n> q\nd\n"
                "## Difficulty Rating\n3/5\n## Adversarial Principles\n- p\n"
                "## How GLA Helps\nh\n## Source\n- **URL**: https://x/1\n"
                "## Tier\ncore\n## API\nopengl\n## Framework\nnone\n"
                "## Bug Signature\n```yaml\ntype: framebuffer_dominant_color\n"
                "spec:\n  color: [1.0, 0.0, 0.0, 1.0]\n  tolerance: 0.1\n```\n"
                "## Predicted GLA Helpfulness\n- **Verdict**: yes\n- **Reasoning**: x\n"
            ),
        },
    )

    fake_runner = MagicMock()
    blue_png = Path(__file__).parent.joinpath(
        "fixtures/curation/framebuffers/solid_blue.png").read_bytes()
    fake_runner.build_and_capture.return_value = {
        "framebuffer_png": blue_png,
        "metadata": {"draw_call_count": 1, "draw_calls": []},
    }

    v = Validator(eval_dir=tmp_path, runner=fake_runner)
    result = v.validate(draft)
    assert result.ok is False
    # Entire dir removed on failure
    assert not (tmp_path / "r_fail").exists()


def test_validator_rejects_preexisting_scenario_dir(tmp_path):
    """If scenario dir already exists, validate() returns ok=False immediately."""
    scenario_id = "r_preexist"
    scenario_dir = tmp_path / scenario_id
    scenario_dir.mkdir()
    (scenario_dir / "main.c").write_text("preexisting content")

    draft = DraftResult(
        scenario_id=scenario_id,
        files={"main.c": "new content", "scenario.md": "# NEW"},
    )
    fake_runner = MagicMock()
    v = Validator(eval_dir=tmp_path, runner=fake_runner)
    result = v.validate(draft)

    assert result.ok is False
    assert "already exists" in result.reason
    # Pre-existing file must be untouched
    assert (scenario_dir / "main.c").read_text() == "preexisting content"
    fake_runner.build_and_capture.assert_not_called()


def test_validator_uses_llm_fallback_on_ambiguous(tmp_path):
    # Arrange: a signature type that returns ambiguous
    llm = MagicMock()
    llm.complete.return_value = LLMResponse(
        text='```json\n{"matches": true, "reason": "looks right"}\n```',
        input_tokens=0, output_tokens=0,
        cache_creation_input_tokens=0, cache_read_input_tokens=0,
        stop_reason="end_turn",
    )
    # Use a signature of type unknown_x which the matcher reports ambiguous for
    md_body = (
        "# R_X\n## Bug\nb\n## Expected Correct Output\ne\n"
        "## Actual Broken Output\na\n## Ground Truth Diagnosis\n> q\nd\n"
        "## Difficulty Rating\n3/5\n## Adversarial Principles\n- p\n"
        "## How GLA Helps\nh\n## Source\n- **URL**: https://x/1\n"
        "## Tier\ncore\n## API\nopengl\n## Framework\nnone\n"
        "## Bug Signature\n```yaml\ntype: unknown_custom\nspec: {}\n```\n"
        "## Predicted GLA Helpfulness\n- **Verdict**: yes\n- **Reasoning**: r\n"
    )
    draft = DraftResult(scenario_id="r_x",
                         c_source="// SOURCE: https://x/1\nint main(){}",
                         md_body=md_body)
    red_png = Path(__file__).parent.joinpath(
        "fixtures/curation/framebuffers/solid_red.png").read_bytes()
    fake_runner = MagicMock()
    fake_runner.build_and_capture.return_value = {
        "framebuffer_png": red_png,
        "metadata": {},
    }
    from gla.eval.curation.validate import Validator
    v = Validator(eval_dir=tmp_path, runner=fake_runner, llm_fallback=llm)
    result = v.validate(draft)
    assert result.ok is True
    assert "LLM fallback" in result.reason
