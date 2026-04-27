"""Rule engine + 8 starter rules for ``gpa check-config``.

Architecture note: YAML carries METADATA (id, severity default,
message template, hint, default_enabled). Python carries LOGIC (a
predicate that walks the GL state dict and returns a Finding or None).
The engine binds them at load time by ``rule_id``.

A "GL state" input here is a dict with keys:

    {
        "frame_id": int,
        "overview": dict,       # FrameOverview as_dict
        "drawcalls": list[dict], # DrawCallInfo as_dict, full pipeline_state
    }

This shape is built by :func:`gpa.api.routes_check_config.build_gl_state`
from a :class:`gpa.backends.base.FrameProvider`. Rules never call back
into the provider — they're pure functions of the dict.
"""

from __future__ import annotations

import functools
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Type

try:  # pragma: no cover - exercised only when PyYAML is unavailable
    import yaml
    _HAVE_YAML = True
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore[assignment]
    _HAVE_YAML = False


# Embedded defaults — used when PyYAML is missing in the runtime
# environment (e.g. the bazel-managed Python 3.11 used by the engine
# launcher). Mirrors ``config_rules.yaml`` exactly. If you change one,
# change the other.
_EMBEDDED_RULES: List[Dict[str, Any]] = [
    {
        "id": "auto-clear-with-no-explicit-clear",
        "severity": "error",
        "default_enabled": True,
        "message": (
            "Frame contains draw calls but no glClear was issued before "
            "the first draw. If renderer.autoClear is false, the framework "
            "expects the app to clear manually — the previous frame's "
            "contents will ghost into this one."
        ),
        "hint": (
            "Either call renderer.clear() at the top of the frame, or "
            "restore renderer.autoClear=true."
        ),
    },
    {
        "id": "color-space-encoding-mismatch",
        "severity": "warn",
        "default_enabled": True,
        "message": (
            "Frame mixes textures with linear (RGBA8) and sRGB "
            "(SRGB8_ALPHA8) internal formats. Sampling them through the "
            "same shader without explicit conversion causes washed-out "
            "or over-saturated output."
        ),
        "hint": (
            "Pick one color space per material slot and set "
            "texture.colorSpace (three.js) or set the equivalent flag on "
            "the framework's image loader."
        ),
    },
    {
        "id": "tone-mapping-on-non-float-target",
        "severity": "warn",
        "default_enabled": True,
        "message": (
            "Tone-mapping precondition triggered: HDR-format inputs are "
            "sampled but every active render target is RGBA8. The "
            "tone-mapping output will band visibly."
        ),
        "hint": (
            "Either disable renderer.toneMapping (NoToneMapping) or "
            "render to an RGBA16F target before the final blit."
        ),
    },
    {
        "id": "premultiplied-alpha-incoherence",
        "severity": "warn",
        "default_enabled": True,
        "message": (
            "Frame mixes premultiplied (ONE / ONE_MINUS_SRC_ALPHA) and "
            "straight (SRC_ALPHA / ONE_MINUS_SRC_ALPHA) blend modes "
            "across draw calls. Without per-material alignment this "
            "produces double-darkening or halo artefacts at material "
            "boundaries."
        ),
        "hint": (
            "Decide on one alpha convention per scene. In three.js, "
            "set material.premultipliedAlpha consistently or disable "
            "transparency on materials that should be opaque."
        ),
    },
    {
        "id": "depth-write-without-depth-test",
        "severity": "warn",
        "default_enabled": True,
        "message": (
            "One or more draws have GL_DEPTH_TEST disabled but "
            "glDepthMask(GL_TRUE) — the depth buffer is being written "
            "through without being read."
        ),
        "hint": (
            "Set material.depthWrite=false on transparent / overlay "
            "materials whose depth buffer state should not leak into "
            "later passes."
        ),
    },
    {
        "id": "viewport-not-equal-framebuffer-size",
        "severity": "info",
        "default_enabled": True,
        "message": (
            "Default framebuffer is bound but glViewport does not "
            "match the framebuffer's dimensions."
        ),
        "hint": (
            "Confirm renderer.setSize() and renderer.setPixelRatio() "
            "are being called after CSS resize. Off-screen passes "
            "(FBO != 0) are excluded from this check."
        ),
    },
    {
        "id": "mipmap-on-npot-without-min-filter",
        "severity": "warn",
        "default_enabled": True,
        "message": (
            "One or more bound textures have non-power-of-two "
            "dimensions. On WebGL1 (and on GLES2 without "
            "OES_texture_npot), sampling these with a mipmap-requiring "
            "min_filter renders fully black."
        ),
        "hint": (
            "Either resize the texture to a power-of-two, or set "
            "texture.minFilter = THREE.LinearFilter (no mipmap) before "
            ".needsUpdate = true."
        ),
    },
    {
        "id": "unused-uniform-set",
        "severity": "info",
        "default_enabled": False,
        "message": (
            "Rule disabled — needs a per-shader active-uniform list "
            "from the capture backend; not yet exposed by FrameProvider."
        ),
        "hint": (
            "Once FrameProvider exposes shader_active_uniforms, this "
            "rule will fire when uniforms are set but never declared "
            "in the compiled program."
        ),
    },
]

# ---------------------------------------------------------------------------
# Severity ordering. Higher number = more severe.
# ---------------------------------------------------------------------------

SEVERITY_ORDER: Dict[str, int] = {"info": 0, "warn": 1, "error": 2}


def _severity_at_or_above(value: str, threshold: str) -> bool:
    return SEVERITY_ORDER.get(value, 0) >= SEVERITY_ORDER.get(threshold, 1)


# ---------------------------------------------------------------------------
# Public dataclasses
# ---------------------------------------------------------------------------


@dataclass
class Finding:
    """One rule fire on one frame.

    Kept small on purpose — agents pay context tokens for every byte.
    ``evidence`` is the only free-form field; rules should put just
    enough GL state to make the finding actionable (3–6 small keys).
    """

    rule_id: str
    severity: str
    message: str
    hint: str = ""
    evidence: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Rule ABC
# ---------------------------------------------------------------------------


class Rule(ABC):
    """Abstract base for one config-rule predicate.

    Subclasses set the class attribute ``id`` (matched to YAML metadata).
    The default ``severity`` is overridden from YAML; the default
    ``message`` / ``hint`` likewise come from YAML.
    """

    id: str = ""
    # The runtime values get overridden when the rule is registered with
    # an engine (engine.register_rule reads the YAML row and patches
    # these onto the instance).
    severity: str = "warn"
    message_template: str = ""
    hint: str = ""
    enabled_by_default: bool = True

    def applies_to(self, gl_state: Dict[str, Any]) -> bool:  # noqa: D401
        """Cheap pre-filter; default = always applies."""
        return True

    @abstractmethod
    def check(self, gl_state: Dict[str, Any]) -> Optional[Finding]:
        """Return a :class:`Finding` if the rule fires, else ``None``."""
        ...

    # --- helpers shared by rules --------------------------------------

    def _finding(self, *, message: Optional[str] = None,
                 hint: Optional[str] = None,
                 evidence: Optional[Dict[str, Any]] = None) -> Finding:
        return Finding(
            rule_id=self.id,
            severity=self.severity,
            message=message if message is not None else self.message_template,
            hint=hint if hint is not None else self.hint,
            evidence=evidence or {},
        )


# ---------------------------------------------------------------------------
# Concrete rules (Phase 1: 8 starter rules)
# ---------------------------------------------------------------------------
#
# Inference notes (per task instructions):
#
# - The 8 rules in this module are derived from the spec's *intent* — flag
#   plausible framework-config bugs that manifest in captured GL state. The
#   spec gives explicit names for the 8 rules in §2.2; we mapped each one
#   onto FrameProvider fields available today (FrameOverview + DrawCallInfo
#   pipeline_state + textures + params).
# - Where the spec mentions framework-only state ("renderer.toneMapping",
#   "physicallyCorrectLights"), we infer the GL signature from the captured
#   state alone. Examples:
#   - tonemap-on-non-float-target: every active color attachment uses an
#     LDR format (RGBA8 / RGB8). With no annotation we can't tell whether
#     tonemap is *on*, but we can flag "any draw with HDR-style blending
#     against an LDR target", a precondition that frequently combines
#     with toneMapping !== NoToneMapping.
#   - color-space-encoding-mismatch: any sampled texture with a non-sRGB
#     internalFormat that would cause linear-vs-sRGB output mismatch.
# - Rules whose required field is not currently in the provider are stubbed
#   with a TODO comment + severity downgraded to ``info`` (see
#   ``UnusedUniformSetRule``).


def _drawcall_count(state: Dict[str, Any]) -> int:
    return len(state.get("drawcalls", []) or [])


def _overview(state: Dict[str, Any]) -> Dict[str, Any]:
    return state.get("overview", {}) or {}


def _drawcalls(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    return list(state.get("drawcalls", []) or [])


def _as_str(value: Any) -> str:
    """Normalize a GL enum to a string. Native backend may return ints."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value.upper()
    return str(value)


# ---- Rule 1: auto-clear-with-no-explicit-clear ----------------------------


class AutoClearWithNoExplicitClearRule(Rule):
    """Frame had at least one draw but no glClear was issued before it.

    Spec §2.2 names this rule. We approximate the trigger using the GL
    state: ``overview.clear_count`` is zero AND there is at least one
    draw call. (When framework annotation is available, the rule can
    additionally key on ``renderer.autoClear === false``; today the GL
    side already gives us a high-signal version.)
    """

    id = "auto-clear-with-no-explicit-clear"

    def applies_to(self, gl_state: Dict[str, Any]) -> bool:
        return _drawcall_count(gl_state) > 0

    def check(self, gl_state: Dict[str, Any]) -> Optional[Finding]:
        ov = _overview(gl_state)
        clear_count = int(ov.get("clear_count", 0) or 0)
        dc_count = _drawcall_count(gl_state)
        if clear_count > 0 or dc_count == 0:
            return None
        return self._finding(
            evidence={
                "clear_count": clear_count,
                "draw_call_count": dc_count,
            }
        )


# ---- Rule 2: color-space-encoding-mismatch --------------------------------


_LINEAR_FORMATS = {
    "RGBA8", "RGB8", "RGBA16F", "RGB16F", "RGBA32F", "RGB32F",
}
_SRGB_FORMATS = {"SRGB8", "SRGB8_ALPHA8"}


class ColorSpaceEncodingMismatchRule(Rule):
    """Texture is sampled as if linear but format suggests sRGB use, or
    vice versa. Captures the common three.js ``colorSpace`` mistake.

    Today we flag the simple GL-only signature: a draw call samples
    a texture whose ``format`` is plain ``RGBA8`` while at least one
    other texture in the same frame uses an explicit ``SRGB8_ALPHA8``
    format — the mismatch is the smoking gun. This is a heuristic but
    is high-precision in practice for the three.js bug class.
    """

    id = "color-space-encoding-mismatch"

    def check(self, gl_state: Dict[str, Any]) -> Optional[Finding]:
        formats: Dict[int, str] = {}
        for dc in _drawcalls(gl_state):
            for t in dc.get("textures") or []:
                tex_id = t.get("texture_id")
                fmt = _as_str(t.get("format"))
                if tex_id and fmt:
                    formats[int(tex_id)] = fmt
        seen_linear = {tid: f for tid, f in formats.items() if f in _LINEAR_FORMATS}
        seen_srgb = {tid: f for tid, f in formats.items() if f in _SRGB_FORMATS}
        if not seen_linear or not seen_srgb:
            return None
        # Mismatch — at least one linear texture is mixed with at least
        # one sRGB texture. Surface the offending ids.
        return self._finding(
            evidence={
                "linear_textures": sorted(seen_linear.keys())[:6],
                "srgb_textures": sorted(seen_srgb.keys())[:6],
            }
        )


# ---- Rule 3: tone-mapping-on-non-float-target -----------------------------


class ToneMappingOnNonFloatTargetRule(Rule):
    """Every color attachment in the frame is an LDR (8-bit-per-channel)
    format. If the framework also turns on tone mapping (we can't see
    that without an annotation today, but the GL precondition still
    rates a warn), the result will band noticeably.

    The GL-side signature: at least one draw call samples a textur with
    a high-dynamic-range format (RGBA16F/RGBA32F) AND every render
    target is RGBA8. That's the common ``toneMapping !== NoToneMapping``
    + 8-bit target combo.
    """

    id = "tone-mapping-on-non-float-target"

    def check(self, gl_state: Dict[str, Any]) -> Optional[Finding]:
        dcs = _drawcalls(gl_state)
        if not dcs:
            return None
        any_hdr_input = False
        ldr_targets: List[int] = []
        hdr_targets = 0
        for dc in dcs:
            for t in dc.get("textures") or []:
                fmt = _as_str(t.get("format"))
                if fmt in {"RGBA16F", "RGBA32F", "RGB16F", "RGB32F"}:
                    any_hdr_input = True
            tex = dc.get("fbo_color_attachment_tex", 0) or 0
            if not tex:
                continue
            # We only know the format of the attachment when it's also
            # bound as a sampler in some draw call (no per-texture
            # registry today). Best-effort heuristic.
            for t in dc.get("textures") or []:
                if t.get("texture_id") == tex:
                    fmt = _as_str(t.get("format"))
                    if fmt in {"RGBA8", "RGB8"}:
                        ldr_targets.append(int(tex))
                    elif fmt in {"RGBA16F", "RGBA32F", "RGB16F", "RGB32F"}:
                        hdr_targets += 1
        if not any_hdr_input or hdr_targets > 0 or not ldr_targets:
            return None
        return self._finding(
            evidence={
                "ldr_render_targets": sorted(set(ldr_targets))[:6],
                "hdr_input_seen": True,
            }
        )


# ---- Rule 4: premultiplied-alpha-incoherence ------------------------------


class PremultipliedAlphaIncoherenceRule(Rule):
    """Blend equation looks like straight-alpha (``SRC_ALPHA, ONE_MINUS_SRC_ALPHA``)
    AND the texture format suggests premultiplied (RGBA8) — or vice
    versa. The classic three.js material.premultipliedAlpha bug.

    GL-side signature today: at least one draw enables blending with
    ``ONE / ONE_MINUS_SRC_ALPHA`` (premultiplied) AND at least one draw
    enables blending with ``SRC_ALPHA / ONE_MINUS_SRC_ALPHA`` (straight)
    in the same frame. Mixed mode = incoherent.
    """

    id = "premultiplied-alpha-incoherence"

    def check(self, gl_state: Dict[str, Any]) -> Optional[Finding]:
        modes: Dict[str, int] = {}
        for dc in _drawcalls(gl_state):
            ps = dc.get("pipeline_state") or {}
            if not ps.get("blend_enabled"):
                continue
            src = _as_str(ps.get("blend_src"))
            dst = _as_str(ps.get("blend_dst"))
            key = f"{src}/{dst}"
            modes[key] = modes.get(key, 0) + 1
        if len(modes) < 2:
            return None
        # Surface up to 4 distinct modes seen.
        return self._finding(
            evidence={
                "blend_modes_seen": sorted(modes.keys())[:4],
                "draw_calls_with_blend": sum(modes.values()),
            }
        )


# ---- Rule 5: depth-write-without-depth-test ------------------------------


class DepthWriteWithoutDepthTestRule(Rule):
    """``glDepthMask(GL_TRUE)`` while ``GL_DEPTH_TEST`` is disabled.

    Often unintentional: write goes through but the frame's depth
    buffer is no longer self-consistent against later draws.
    Captured directly in ``pipeline_state`` per draw call.
    """

    id = "depth-write-without-depth-test"

    def check(self, gl_state: Dict[str, Any]) -> Optional[Finding]:
        offenders: List[int] = []
        for dc in _drawcalls(gl_state):
            ps = dc.get("pipeline_state") or {}
            if ps.get("depth_write_enabled") and not ps.get("depth_test_enabled"):
                offenders.append(int(dc.get("id", -1)))
        if not offenders:
            return None
        return self._finding(
            evidence={
                "draw_call_ids": offenders[:8],
                "offender_count": len(offenders),
            }
        )


# ---- Rule 6: viewport-not-equal-framebuffer-size --------------------------


class ViewportNotEqualFramebufferSizeRule(Rule):
    """``glViewport`` does not match the framebuffer size.

    Common when ``renderer.pixelRatio`` is wrong or the framework
    forgets to call ``setSize`` after a CSS resize. Severity ``info``
    because deliberate offscreen passes also trigger this — but for
    the *default* framebuffer it's almost always wrong.
    """

    id = "viewport-not-equal-framebuffer-size"

    def check(self, gl_state: Dict[str, Any]) -> Optional[Finding]:
        ov = _overview(gl_state)
        fb_w = int(ov.get("fb_width", 0) or 0)
        fb_h = int(ov.get("fb_height", 0) or 0)
        if fb_w == 0 or fb_h == 0:
            return None
        offenders: List[Dict[str, Any]] = []
        for dc in _drawcalls(gl_state):
            ps = dc.get("pipeline_state") or {}
            vp_w = int(ps.get("viewport_w", 0) or 0)
            vp_h = int(ps.get("viewport_h", 0) or 0)
            # Skip draws that look like off-screen passes (FBO != 0).
            if dc.get("fbo_color_attachment_tex"):
                continue
            if vp_w == 0 or vp_h == 0:
                continue
            if vp_w != fb_w or vp_h != fb_h:
                offenders.append({
                    "dc_id": int(dc.get("id", -1)),
                    "viewport": [vp_w, vp_h],
                })
        if not offenders:
            return None
        return self._finding(
            evidence={
                "framebuffer_size": [fb_w, fb_h],
                "examples": offenders[:4],
            }
        )


# ---- Rule 7: mipmap-on-npot-without-min-filter ----------------------------


class MipmapOnNpotWithoutMinFilterRule(Rule):
    """Texture has non-power-of-two dimensions but is sampled with a
    mipmap-requiring filter.

    GL-side: any bound texture whose width or height is not a power of
    two. We don't currently capture min_filter per texture binding
    (TODO once FrameProvider exposes it). For now we flag NPOT
    textures so the agent at least surfaces them.
    """

    id = "mipmap-on-npot-without-min-filter"

    @staticmethod
    def _is_pow2(n: int) -> bool:
        return n > 0 and (n & (n - 1)) == 0

    def check(self, gl_state: Dict[str, Any]) -> Optional[Finding]:
        npot: List[Dict[str, Any]] = []
        seen: set[int] = set()
        for dc in _drawcalls(gl_state):
            for t in dc.get("textures") or []:
                tid = int(t.get("texture_id", 0) or 0)
                if tid in seen or tid == 0:
                    continue
                w = int(t.get("width", 0) or 0)
                h = int(t.get("height", 0) or 0)
                if w == 0 or h == 0:
                    continue
                if not self._is_pow2(w) or not self._is_pow2(h):
                    npot.append({"texture_id": tid, "width": w, "height": h})
                    seen.add(tid)
        if not npot:
            return None
        return self._finding(
            evidence={
                "npot_textures": npot[:6],
                "note": (
                    "min_filter not currently captured per binding; "
                    "any of these used with GL_LINEAR_MIPMAP_LINEAR will "
                    "render fully-black on WebGL1."
                ),
            }
        )


# ---- Rule 8: unused-uniform-set (info-only stub) --------------------------


class UnusedUniformSetRule(Rule):
    """Uniform location was set but the shader does not consume it.

    NOTE: requires a per-shader active-uniform list cross-referenced
    with the per-draw uniform-set list. We capture the set list today
    (``dc.params``) but not the *active* list — that requires a new
    FrameProvider field. Disabled with severity=info until that lands.
    """

    id = "unused-uniform-set"

    def applies_to(self, gl_state: Dict[str, Any]) -> bool:
        return False  # disabled; check() never runs

    def check(self, gl_state: Dict[str, Any]) -> Optional[Finding]:
        # TODO: once FrameProvider exposes per-shader active-uniform
        # introspection (e.g. dc.shader_active_uniforms), compare it
        # against dc.params and surface set-but-not-declared cases.
        return None


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


_DEFAULT_YAML_PATH = Path(__file__).with_name("config_rules.yaml")


# Registry of Python predicate classes by id. Importing this module
# triggers registration via the class definitions above; the engine
# wires the YAML metadata onto each instance.
_PYTHON_RULES: Dict[str, Type[Rule]] = {
    cls.id: cls
    for cls in (
        AutoClearWithNoExplicitClearRule,
        ColorSpaceEncodingMismatchRule,
        ToneMappingOnNonFloatTargetRule,
        PremultipliedAlphaIncoherenceRule,
        DepthWriteWithoutDepthTestRule,
        ViewportNotEqualFramebufferSizeRule,
        MipmapOnNpotWithoutMinFilterRule,
        UnusedUniformSetRule,
    )
    if cls.id  # safety: skip empty-id stubs
}


class RuleEngine:
    """Loads rule metadata from YAML, binds Python predicates, runs rules."""

    def __init__(self, rules: List[Rule]):
        self._rules: List[Rule] = list(rules)

    @classmethod
    def from_yaml(cls, yaml_path: Optional[Path] = None) -> "RuleEngine":
        """Load rules from YAML if available; otherwise from in-process defaults.

        The bazel-managed Python 3.11 used by the engine launcher does not
        ship PyYAML by default, so we fall back to ``_EMBEDDED_RULES``
        — they are kept byte-for-byte equivalent to the YAML file.
        """
        if _HAVE_YAML:
            path = Path(yaml_path) if yaml_path else _DEFAULT_YAML_PATH
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    doc = yaml.safe_load(fh) or {}
                entries = doc.get("rules", []) or []
            except FileNotFoundError:
                entries = _EMBEDDED_RULES
        else:
            entries = _EMBEDDED_RULES
        rules: List[Rule] = []
        for entry in entries:
            rid = entry.get("id")
            if not rid:
                continue
            cls_for = _PYTHON_RULES.get(rid)
            if cls_for is None:
                # YAML-only rule with no Python implementation; skip.
                continue
            inst = cls_for()
            inst.severity = entry.get("severity", inst.severity)
            inst.message_template = entry.get("message", inst.message_template)
            inst.hint = entry.get("hint", inst.hint)
            inst.enabled_by_default = bool(entry.get("default_enabled", True))
            rules.append(inst)
        # Append any Python rule that has no YAML row (defensive — keeps
        # the engine usable if YAML is empty during tests).
        seen_ids = {r.id for r in rules}
        for rid, cls_for in _PYTHON_RULES.items():
            if rid not in seen_ids:
                inst = cls_for()
                rules.append(inst)
        return cls(rules)

    # ---- Introspection ------------------------------------------------

    def all_rules(self) -> List[Rule]:
        return list(self._rules)

    def rule_ids(self) -> List[str]:
        return [r.id for r in self._rules]

    def get_rule(self, rule_id: str) -> Optional[Rule]:
        for r in self._rules:
            if r.id == rule_id:
                return r
        return None

    # ---- Evaluation ---------------------------------------------------

    def run(
        self,
        gl_state: Dict[str, Any],
        *,
        rule_ids: Optional[Iterable[str]] = None,
        min_severity: str = "warn",
    ) -> List[Finding]:
        """Run a filtered subset of rules against ``gl_state``.

        Args:
            gl_state: dict with ``overview`` + ``drawcalls`` keys.
            rule_ids: if not None, only run rules whose id is in this set.
                Default = run all rules whose ``enabled_by_default`` is True.
            min_severity: drop findings whose severity ranks below this.

        Returns:
            Findings sorted by severity (desc) then rule_id.
        """
        wanted: Optional[set[str]] = None
        if rule_ids is not None:
            wanted = {r for r in rule_ids if r}
        findings: List[Finding] = []
        for rule in self._rules:
            if wanted is not None:
                if rule.id not in wanted:
                    continue
            else:
                if not rule.enabled_by_default:
                    continue
            try:
                if not rule.applies_to(gl_state):
                    continue
                f = rule.check(gl_state)
            except Exception as exc:  # noqa: BLE001
                # A crashing rule shouldn't poison the whole report.
                f = Finding(
                    rule_id=rule.id,
                    severity="info",
                    message=f"rule predicate crashed: {exc}",
                    hint="",
                    evidence={},
                )
            if f is None:
                continue
            if not _severity_at_or_above(f.severity, min_severity):
                continue
            findings.append(f)
        # Sort: severity desc, then rule_id asc.
        findings.sort(
            key=lambda x: (-SEVERITY_ORDER.get(x.severity, 0), x.rule_id)
        )
        return findings

    def evaluated_rule_ids(
        self, *, rule_ids: Optional[Iterable[str]] = None
    ) -> List[str]:
        """List of rule ids the engine *would* execute given the filter."""
        wanted: Optional[set[str]] = None
        if rule_ids is not None:
            wanted = {r for r in rule_ids if r}
        out: List[str] = []
        for rule in self._rules:
            if wanted is not None:
                if rule.id not in wanted:
                    continue
            elif not rule.enabled_by_default:
                continue
            out.append(rule.id)
        return sorted(out)


@functools.lru_cache(maxsize=1)
def default_engine() -> RuleEngine:
    """Process-wide default engine, loaded from in-tree YAML."""
    return RuleEngine.from_yaml()
