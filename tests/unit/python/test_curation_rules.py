from gpa.eval.curation.discover import DiscoveryCandidate
from gpa.eval.curation.rules import score_candidate, select_stratified
from gpa.eval.curation.triage import IssueThread


def make_synthetic_candidate(*, body: str, url: str, has_fix_pr_linked: bool):
    """Build a synthetic DiscoveryCandidate with the body embedded in metadata.

    When ``has_fix_pr_linked=True``, append a closing-PR reference so the
    ``fix_pr_linked`` triage_required group matches.
    """
    if has_fix_pr_linked and "Closed by #" not in body and "pull/" not in body:
        body = f"{body}\n\nClosed by #2"
    cand = DiscoveryCandidate(
        url=url,
        source_type="issue",
        title="synthetic",
        labels=[],
        metadata={"body": body},
    )
    return cand


def test_score_stackoverflow_threejs_user_config():
    cand = DiscoveryCandidate(
        url="https://stackoverflow.com/questions/37647853/depthwrite",
        source_type="stackoverflow",
        title="Three.js transparent points depthWrite problem",
        labels=["three.js"],
    )
    thread = IssueThread(
        url=cand.url,
        title=cand.title,
        # "wrong" satisfies the visual_keyword_present triage_required group;
        # "Closed by #4242" satisfies fix_pr_linked.
        body="Transparent points overlap incorrectly and look wrong.",
        comments=[
            "=== Accepted Answer (score: 61) ===\n"
            "Use depthWrite false for transparent points; depth and blending "
            "do not work together in this case.\n\nClosed by #4242"
        ],
    )

    rec = score_candidate(cand, thread)

    assert rec.category == "framework-app-dev"
    assert rec.subcategory == "web-3d"
    assert rec.framework == "three.js"
    assert rec.bug_class_guess == "user-config"
    assert rec.score >= 6
    assert "gpu:depth_blend_state" in rec.reason_codes
    assert "resolution:accepted_answer" in rec.reason_codes


def test_score_framework_repo_not_planned_can_be_app_dev():
    cand = DiscoveryCandidate(
        url="https://github.com/mrdoob/three.js/issues/31132",
        source_type="issue",
        title="WebGPURenderer images with metadata produce different result",
        labels=["Browser Issue"],
    )
    thread = IssueThread(
        url=cand.url,
        title=cand.title,
        # "wrong" satisfies visual_keyword_present; "Closed by" satisfies fix_pr_linked.
        body="WebGPU and WebGL render the same PNG texture with wrong, different colors.",
        comments=[
            "The workaround is colorSpaceConversion none and premultiplyAlpha none.\n\n"
            "Closed by #31200"
        ],
    )

    rec = score_candidate(cand, thread)

    assert rec.category == "framework-app-dev"
    assert rec.subcategory == "web-3d"
    assert rec.framework == "three.js"
    assert rec.score > 0
    assert "gpu:color_pipeline" in rec.reason_codes


def test_select_stratified_caps_per_taxonomy_cell():
    records = []
    for i in range(5):
        cand = DiscoveryCandidate(
            url=f"https://stackoverflow.com/questions/{i}/depthwrite",
            source_type="stackoverflow",
            title=f"Three.js transparent depthWrite {i}",
            labels=["three.js"],
        )
        records.append(score_candidate(cand, IssueThread(
            url=cand.url,
            title=cand.title,
            body="Transparent wrong output with depthWrite.",
            comments=[
                "=== Accepted Answer (score: 2) ===\nset depthWrite false\n\n"
                "Closed by #1"
            ],
        )))
    for i in range(3):
        cand = DiscoveryCandidate(
            url=f"https://stackoverflow.com/questions/9{i}/shadow",
            source_type="stackoverflow",
            title=f"React Three Fiber cropped shadow {i}",
            labels=["react-three-fiber"],
        )
        records.append(score_candidate(cand, IssueThread(
            url=cand.url,
            title=cand.title,
            # "missing" satisfies visual_keyword_present.
            body="Shadows are cropped in a rectangular region; corners look missing.",
            comments=[
                "=== Accepted Answer (score: 2) ===\nset shadow-camera-left\n\n"
                "Closed by #1"
            ],
        )))

    selected = select_stratified(records, top_k=4, min_score=1, per_cell_cap=2)

    assert len(selected) == 4
    counts = {}
    for rec in selected:
        counts[rec.taxonomy_cell] = counts.get(rec.taxonomy_cell, 0) + 1
    assert max(counts.values()) == 2
    assert all(rec.selected for rec in selected)


def test_classify_score_drops_when_triage_required_unmet():
    from gpa.eval.curation.rules import score_candidate, load_rules
    rules = load_rules()  # default rules file
    cand = make_synthetic_candidate(
        body="Cubes flicker on Vulkan. Repro: ...",
        url="https://github.com/x/y/issues/99",
        has_fix_pr_linked=False,
    )
    rec = score_candidate(cand, thread=None, rules=rules)
    assert rec.terminal_reason == "triage_rejected"
    assert "missing_fix_pr_linked" in rec.score_reasons


def test_classify_score_drops_feature_request_via_reject_rule():
    from gpa.eval.curation.rules import score_candidate, load_rules
    rules = load_rules()
    cand = make_synthetic_candidate(
        body=(
            "Feature request: please add a depth-of-field shader. "
            "Currently glitches when missing inputs."
        ),
        url="https://github.com/x/y/issues/100",
        has_fix_pr_linked=True,
    )
    rec = score_candidate(cand, thread=None, rules=rules)
    assert rec.terminal_reason == "triage_rejected"
    assert "feature_request" in rec.score_reasons


def test_visual_keyword_accepts_expanded_terms():
    """Bodies using 'incorrect', 'broken', 'fails', 'regression', 'crash',
    'corrupted', 'distortion' should now satisfy the visual_keyword_present
    gate (previously rejected as 'missing_visual_keyword_present')."""
    from gpa.eval.curation.rules import score_candidate, load_rules
    rules = load_rules()
    expanded_terms = [
        "Rendering is incorrect when alpha blending is on.",
        "The shader is broken on Metal backend.",
        "Texture upload fails for compressed formats.",
        "This is a regression from 4.2 — colors are off.",
        "WebGL2 crashes when uploading large textures.",
        "Output texture is corrupted on AMD GPUs.",
        "Heavy distortion in fragment output near edges.",
    ]
    for body in expanded_terms:
        cand = make_synthetic_candidate(
            body=body,
            url="https://github.com/x/y/issues/1",
            has_fix_pr_linked=True,
        )
        rec = score_candidate(cand, thread=None, rules=rules)
        assert rec.terminal_reason != "triage_rejected", (
            f"body {body!r} should pass visual_keyword_present "
            f"but was rejected: {rec.score_reasons}"
        )


def test_pr_url_auto_satisfies_fix_pr_linked():
    """A merged PR URL on the candidate should auto-satisfy fix_pr_linked
    even when the body has no explicit 'Closes #N' reference. A merged PR
    is itself the fix; requiring a separate referencing PR rejects valid
    candidates (~25% of fix_pr_linked rejections in the smoke-test sample)."""
    from gpa.eval.curation.rules import score_candidate, load_rules
    rules = load_rules()
    cand = DiscoveryCandidate(
        url="https://github.com/foo/bar/pull/12345",
        source_type="pr",
        title="fix: shadow camera bounds wrong on resize",
        labels=[],
        metadata={
            "body": "This PR fixes the shadow camera which was rendering "
                    "incorrect bounds after window resize.",
        },
    )
    rec = score_candidate(cand, thread=None, rules=rules)
    assert rec.terminal_reason != "triage_rejected", rec.score_reasons


def test_issue_url_does_not_auto_satisfy_fix_pr_linked():
    """An issue URL (.../issues/<n>) without a closing-PR reference must
    still fail fix_pr_linked. Confirms the URL match is PR-specific."""
    from gpa.eval.curation.rules import score_candidate, load_rules
    rules = load_rules()
    cand = make_synthetic_candidate(
        body="Rendering is broken on Metal.",
        url="https://github.com/x/y/issues/77",
        has_fix_pr_linked=False,
    )
    rec = score_candidate(cand, thread=None, rules=rules)
    assert rec.terminal_reason == "triage_rejected"
    assert "missing_fix_pr_linked" in rec.score_reasons
