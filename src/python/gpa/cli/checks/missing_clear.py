"""``missing-clear`` diagnostic — drawing without a preceding glClear."""

from __future__ import annotations

from typing import Optional

from gpa.cli.checks import Check, CheckResult, Finding, register


@register
class MissingClearCheck(Check):
    name = "missing-clear"

    def run(self, client, *, frame_id: int, dc_id: Optional[int] = None) -> CheckResult:
        overview = client.get_json(f"/api/v1/frames/{frame_id}/overview")
        clear_count = int(overview.get("clear_count", 0) or 0)
        draw_count = int(overview.get("draw_call_count", 0) or 0)
        if clear_count == 0 and draw_count > 0:
            return CheckResult(
                name=self.name,
                status="warn",
                findings=[
                    Finding(
                        summary=(
                            f"frame {frame_id} has {draw_count} draw calls "
                            f"but no glClear"
                        ),
                        detail={
                            "frame_id": frame_id,
                            "draw_call_count": draw_count,
                            "clear_count": clear_count,
                        },
                    )
                ],
            )
        return CheckResult(name=self.name, status="ok")
