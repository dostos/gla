"""``empty-capture`` diagnostic — warn if a frame has zero draw calls."""

from __future__ import annotations

from typing import Optional

from gpa.cli.checks import Check, CheckResult, Finding, register


@register
class EmptyCaptureCheck(Check):
    name = "empty-capture"

    def run(self, client, *, frame_id: int, dc_id: Optional[int] = None) -> CheckResult:
        overview = client.get_json(f"/api/v1/frames/{frame_id}/overview")
        draw_count = int(overview.get("draw_call_count", 0) or 0)
        if draw_count == 0:
            return CheckResult(
                name=self.name,
                status="warn",
                findings=[
                    Finding(
                        summary="frame contains zero draw calls",
                        detail={"frame_id": frame_id, "draw_call_count": 0},
                    )
                ],
            )
        return CheckResult(name=self.name, status="ok")
