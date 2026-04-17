from unittest.mock import MagicMock
from pathlib import Path
from gla.eval.curation.validate import Validator, ValidationResult
from gla.eval.curation.draft import DraftResult

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
    # The C source and md were written to tmp_path
    assert (tmp_path / "r_test_ok.c").exists()
    assert (tmp_path / "r_test_ok.md").exists()

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
