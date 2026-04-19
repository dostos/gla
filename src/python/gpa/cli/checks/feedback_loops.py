"""``feedback-loops`` diagnostic — sample-from-render-target bugs.

For each draw call in the frame, GET /feedback-loops and surface any
bound textures that collide with the current FBO's color attachment.
"""

from __future__ import annotations

from typing import Optional

from gpa.cli.checks import Check, CheckResult, Finding, register


def _iter_drawcalls(client, frame_id: int):
    """Yield all draw calls for a frame, paginating defensively.

    Stops when the engine returns an empty page or fewer items than
    requested (the provider's usual "short read = end" convention).  The
    short-read check prevents infinite loops against mocks that ignore
    the ``offset`` argument.
    """
    offset = 0
    limit = 200
    seen = 0
    while True:
        page = client.get_json(
            f"/api/v1/frames/{frame_id}/drawcalls?limit={limit}&offset={offset}"
        )
        items = page.get("items", []) if isinstance(page, dict) else []
        if not items:
            return
        for dc in items:
            yield dc
        seen += len(items)
        total = int(page.get("total", seen)) if isinstance(page, dict) else seen
        if len(items) < limit or seen >= total:
            return
        offset += len(items)


@register
class FeedbackLoopsCheck(Check):
    name = "feedback-loops"

    def run(self, client, *, frame_id: int, dc_id: Optional[int] = None) -> CheckResult:
        findings: list[Finding] = []

        ids: list[int]
        if dc_id is not None:
            ids = [int(dc_id)]
        else:
            ids = [int(dc["id"]) for dc in _iter_drawcalls(client, frame_id)]

        for did in ids:
            resp = client.get_json(
                f"/api/v1/frames/{frame_id}/drawcalls/{did}/feedback-loops"
            )
            textures = resp.get("textures") or []
            if not textures:
                continue
            fbo_tex = resp.get("fbo_color_attachment_tex", 0)
            for tex in textures:
                slot = tex.get("slot")
                tex_id = tex.get("texture_id")
                findings.append(
                    Finding(
                        summary=(
                            f"draw call {did}: texture {tex_id} bound as "
                            f"sampler (slot {slot}) AND COLOR_ATTACHMENT0"
                        ),
                        detail={
                            "dc_id": did,
                            "fbo_color_attachment_tex": fbo_tex,
                            "slot": slot,
                            "texture_id": tex_id,
                            "width": tex.get("width"),
                            "height": tex.get("height"),
                        },
                    )
                )
        status = "warn" if findings else "ok"
        return CheckResult(name=self.name, status=status, findings=findings)
