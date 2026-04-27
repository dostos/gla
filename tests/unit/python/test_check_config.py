"""Unit tests for the rule engine + 8 starter rules."""
from __future__ import annotations

from typing import Any, Dict

import pytest

from gpa.checks import Finding, RuleEngine, default_engine
from gpa.checks.rules import (
    AutoClearWithNoExplicitClearRule,
    ColorSpaceEncodingMismatchRule,
    DepthWriteWithoutDepthTestRule,
    MipmapOnNpotWithoutMinFilterRule,
    PremultipliedAlphaIncoherenceRule,
    SEVERITY_ORDER,
    ToneMappingOnNonFloatTargetRule,
    UnusedUniformSetRule,
    ViewportNotEqualFramebufferSizeRule,
    _PYTHON_RULES,
)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _state(*, drawcalls=None, fb=(800, 600), clear_count=0) -> Dict[str, Any]:
    fb_w, fb_h = fb
    dcs = list(drawcalls or [])
    return {
        "frame_id": 1,
        "overview": {
            "frame_id": 1,
            "draw_call_count": len(dcs),
            "clear_count": clear_count,
            "fb_width": fb_w,
            "fb_height": fb_h,
            "timestamp": 0.0,
        },
        "drawcalls": dcs,
    }


def _dc(
    *,
    dc_id: int = 0,
    blend_enabled: bool = False,
    blend_src: str = "ONE",
    blend_dst: str = "ZERO",
    depth_test: bool = True,
    depth_write: bool = True,
    viewport_w: int = 800,
    viewport_h: int = 600,
    fbo_color_attachment_tex: int = 0,
    textures=None,
) -> Dict[str, Any]:
    return {
        "id": dc_id,
        "primitive_type": "TRIANGLES",
        "vertex_count": 3,
        "index_count": 0,
        "instance_count": 1,
        "shader_id": 1,
        "pipeline_state": {
            "viewport_x": 0,
            "viewport_y": 0,
            "viewport_w": viewport_w,
            "viewport_h": viewport_h,
            "blend_enabled": blend_enabled,
            "blend_src": blend_src,
            "blend_dst": blend_dst,
            "depth_test_enabled": depth_test,
            "depth_write_enabled": depth_write,
        },
        "params": [],
        "textures": list(textures or []),
        "fbo_color_attachment_tex": fbo_color_attachment_tex,
        "fbo_color_attachments": [fbo_color_attachment_tex] + [0] * 7,
        "index_type": 0,
    }


# --------------------------------------------------------------------------- #
# Engine + YAML
# --------------------------------------------------------------------------- #


class TestEngineLoad:
    def test_default_engine_has_all_8_python_rules(self):
        eng = default_engine()
        ids = set(eng.rule_ids())
        assert ids == set(_PYTHON_RULES.keys())
        # 8 starter rules per spec.
        assert len(ids) == 8

    def test_each_rule_has_metadata(self):
        eng = default_engine()
        for r in eng.all_rules():
            assert r.severity in SEVERITY_ORDER
            assert isinstance(r.message_template, str)
            # Even disabled rules must have a non-empty message.
            assert r.message_template

    def test_severity_ordering(self):
        assert SEVERITY_ORDER["error"] > SEVERITY_ORDER["warn"]
        assert SEVERITY_ORDER["warn"] > SEVERITY_ORDER["info"]

    def test_unused_uniform_set_disabled_by_default(self):
        eng = default_engine()
        r = eng.get_rule("unused-uniform-set")
        assert r is not None
        assert r.enabled_by_default is False


# --------------------------------------------------------------------------- #
# Individual rules
# --------------------------------------------------------------------------- #


class TestAutoClear:
    def test_fires_when_draws_present_and_no_clear(self):
        rule = AutoClearWithNoExplicitClearRule()
        rule.message_template = "x"
        rule.severity = "error"
        state = _state(drawcalls=[_dc()], clear_count=0)
        f = rule.check(state)
        assert f is not None
        assert f.severity == "error"
        assert f.evidence["draw_call_count"] == 1

    def test_quiet_when_clear_was_issued(self):
        rule = AutoClearWithNoExplicitClearRule()
        rule.message_template = "x"
        state = _state(drawcalls=[_dc()], clear_count=1)
        assert rule.check(state) is None

    def test_quiet_when_no_drawcalls(self):
        rule = AutoClearWithNoExplicitClearRule()
        rule.message_template = "x"
        state = _state(drawcalls=[], clear_count=0)
        assert rule.applies_to(state) is False


class TestColorSpace:
    def test_fires_on_mixed_linear_and_srgb(self):
        rule = ColorSpaceEncodingMismatchRule()
        rule.message_template = "x"
        state = _state(drawcalls=[
            _dc(textures=[
                {"slot": 0, "texture_id": 1, "width": 256, "height": 256, "format": "RGBA8"},
                {"slot": 1, "texture_id": 2, "width": 256, "height": 256, "format": "SRGB8_ALPHA8"},
            ]),
        ])
        f = rule.check(state)
        assert f is not None
        assert 1 in f.evidence["linear_textures"]
        assert 2 in f.evidence["srgb_textures"]

    def test_quiet_all_linear(self):
        rule = ColorSpaceEncodingMismatchRule()
        rule.message_template = "x"
        state = _state(drawcalls=[
            _dc(textures=[
                {"slot": 0, "texture_id": 1, "width": 256, "height": 256, "format": "RGBA8"},
            ]),
        ])
        assert rule.check(state) is None


class TestToneMapping:
    def test_fires_when_hdr_input_and_ldr_target(self):
        rule = ToneMappingOnNonFloatTargetRule()
        rule.message_template = "x"
        # Same texture id 5 is both the FBO attachment AND a sampled
        # texture with format RGBA8 (LDR), but another draw samples an
        # RGBA16F texture (HDR input).
        state = _state(drawcalls=[
            _dc(
                fbo_color_attachment_tex=5,
                textures=[
                    {"slot": 0, "texture_id": 5, "width": 800, "height": 600, "format": "RGBA8"},
                ],
            ),
            _dc(
                dc_id=1,
                textures=[
                    {"slot": 0, "texture_id": 9, "width": 800, "height": 600, "format": "RGBA16F"},
                ],
            ),
        ])
        f = rule.check(state)
        assert f is not None
        assert 5 in f.evidence["ldr_render_targets"]

    def test_quiet_no_hdr_input(self):
        rule = ToneMappingOnNonFloatTargetRule()
        rule.message_template = "x"
        state = _state(drawcalls=[_dc()])
        assert rule.check(state) is None


class TestPremultipliedAlpha:
    def test_fires_on_mixed_blend_modes(self):
        rule = PremultipliedAlphaIncoherenceRule()
        rule.message_template = "x"
        state = _state(drawcalls=[
            _dc(blend_enabled=True, blend_src="ONE", blend_dst="ONE_MINUS_SRC_ALPHA"),
            _dc(dc_id=1, blend_enabled=True,
                blend_src="SRC_ALPHA", blend_dst="ONE_MINUS_SRC_ALPHA"),
        ])
        f = rule.check(state)
        assert f is not None
        assert len(f.evidence["blend_modes_seen"]) >= 2

    def test_quiet_single_mode(self):
        rule = PremultipliedAlphaIncoherenceRule()
        rule.message_template = "x"
        state = _state(drawcalls=[
            _dc(blend_enabled=True, blend_src="SRC_ALPHA", blend_dst="ONE_MINUS_SRC_ALPHA"),
            _dc(dc_id=1, blend_enabled=True,
                blend_src="SRC_ALPHA", blend_dst="ONE_MINUS_SRC_ALPHA"),
        ])
        assert rule.check(state) is None


class TestDepthWrite:
    def test_fires_on_dw_without_dt(self):
        rule = DepthWriteWithoutDepthTestRule()
        rule.message_template = "x"
        state = _state(drawcalls=[
            _dc(depth_test=False, depth_write=True),
        ])
        f = rule.check(state)
        assert f is not None
        assert 0 in f.evidence["draw_call_ids"]

    def test_quiet_when_dt_enabled(self):
        rule = DepthWriteWithoutDepthTestRule()
        rule.message_template = "x"
        state = _state(drawcalls=[_dc(depth_test=True, depth_write=True)])
        assert rule.check(state) is None


class TestViewport:
    def test_fires_when_viewport_smaller_than_fb(self):
        rule = ViewportNotEqualFramebufferSizeRule()
        rule.message_template = "x"
        state = _state(
            drawcalls=[_dc(viewport_w=400, viewport_h=300)],
            fb=(800, 600),
        )
        f = rule.check(state)
        assert f is not None
        assert f.evidence["framebuffer_size"] == [800, 600]

    def test_quiet_when_match(self):
        rule = ViewportNotEqualFramebufferSizeRule()
        rule.message_template = "x"
        state = _state(drawcalls=[_dc()], fb=(800, 600))
        assert rule.check(state) is None

    def test_skips_offscreen_passes(self):
        rule = ViewportNotEqualFramebufferSizeRule()
        rule.message_template = "x"
        state = _state(
            drawcalls=[_dc(viewport_w=256, viewport_h=256, fbo_color_attachment_tex=9)],
            fb=(800, 600),
        )
        assert rule.check(state) is None


class TestMipmapNpot:
    def test_fires_on_npot_texture(self):
        rule = MipmapOnNpotWithoutMinFilterRule()
        rule.message_template = "x"
        state = _state(drawcalls=[_dc(textures=[
            {"slot": 0, "texture_id": 1, "width": 100, "height": 200, "format": "RGBA8"},
        ])])
        f = rule.check(state)
        assert f is not None
        assert any(t["texture_id"] == 1 for t in f.evidence["npot_textures"])

    def test_quiet_on_pow2(self):
        rule = MipmapOnNpotWithoutMinFilterRule()
        rule.message_template = "x"
        state = _state(drawcalls=[_dc(textures=[
            {"slot": 0, "texture_id": 1, "width": 256, "height": 512, "format": "RGBA8"},
        ])])
        assert rule.check(state) is None


class TestUnusedUniformSet:
    def test_disabled(self):
        rule = UnusedUniformSetRule()
        rule.message_template = "x"
        # applies_to returns False, so check is never reached at runtime.
        state = _state()
        assert rule.applies_to(state) is False
        # And the predicate itself is a no-op.
        assert rule.check(state) is None


# --------------------------------------------------------------------------- #
# Engine.run() — filtering & sort order
# --------------------------------------------------------------------------- #


class TestEngineRun:
    def test_severity_filter_drops_lower(self):
        eng = default_engine()
        # State that fires (a) auto-clear (error), (b) viewport-info,
        # (c) depth-write (warn).
        state = _state(
            drawcalls=[_dc(viewport_w=400, depth_test=False, depth_write=True)],
            clear_count=0,
        )
        info = eng.run(state, min_severity="info")
        warn = eng.run(state, min_severity="warn")
        err = eng.run(state, min_severity="error")
        sevs_info = [f.severity for f in info]
        sevs_warn = [f.severity for f in warn]
        sevs_err = [f.severity for f in err]
        assert "info" in sevs_info
        assert "info" not in sevs_warn  # filter dropped info
        assert sevs_err == ["error"]

    def test_rule_filter_scopes(self):
        eng = default_engine()
        state = _state(
            drawcalls=[_dc(depth_test=False, depth_write=True)],
            clear_count=1,  # so auto-clear does NOT fire
        )
        only = eng.run(
            state,
            rule_ids=["depth-write-without-depth-test"],
            min_severity="info",
        )
        assert len(only) == 1
        assert only[0].rule_id == "depth-write-without-depth-test"

    def test_findings_sorted_severity_desc(self):
        eng = default_engine()
        state = _state(
            drawcalls=[_dc(viewport_w=400, depth_test=False, depth_write=True)],
            clear_count=0,
        )
        findings = eng.run(state, min_severity="info")
        for a, b in zip(findings, findings[1:]):
            assert SEVERITY_ORDER[a.severity] >= SEVERITY_ORDER[b.severity]

    def test_rule_crash_does_not_break_run(self):
        # Inject a deliberately broken rule.
        from gpa.checks.rules import Rule

        class Boom(Rule):
            id = "boom"

            def check(self, gl_state):
                raise RuntimeError("boom")

        boom = Boom()
        boom.message_template = "x"
        boom.severity = "warn"
        eng = RuleEngine([boom])
        state = _state(drawcalls=[_dc()])
        out = eng.run(state, min_severity="info")
        assert len(out) == 1
        assert out[0].severity == "info"
        assert "rule predicate crashed" in out[0].message

    def test_evaluated_rule_ids_default(self):
        eng = default_engine()
        evald = eng.evaluated_rule_ids()
        # Default-disabled rules excluded.
        assert "unused-uniform-set" not in evald
        # All others present.
        assert "auto-clear-with-no-explicit-clear" in evald

    def test_evaluated_rule_ids_with_filter(self):
        eng = default_engine()
        evald = eng.evaluated_rule_ids(rule_ids=["unused-uniform-set"])
        assert evald == ["unused-uniform-set"]


class TestFindingShape:
    def test_to_dict(self):
        f = Finding(
            rule_id="x", severity="warn", message="m", hint="h",
            evidence={"a": 1},
        )
        d = f.to_dict()
        assert d == {
            "rule_id": "x", "severity": "warn",
            "message": "m", "hint": "h",
            "evidence": {"a": 1},
        }
