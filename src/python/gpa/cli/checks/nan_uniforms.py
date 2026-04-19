"""``nan-uniforms`` diagnostic — NaN/Inf components in bound uniforms."""

from __future__ import annotations

from typing import Optional

from gpa.cli.checks import Check, CheckResult, Finding, register
from gpa.cli.checks.feedback_loops import _iter_drawcalls


@register
class NanUniformsCheck(Check):
    name = "nan-uniforms"

    def run(self, client, *, frame_id: int, dc_id: Optional[int] = None) -> CheckResult:
        findings: list[Finding] = []

        if dc_id is not None:
            ids = [int(dc_id)]
        else:
            ids = [int(dc["id"]) for dc in _iter_drawcalls(client, frame_id)]

        for did in ids:
            resp = client.get_json(
                f"/api/v1/frames/{frame_id}/drawcalls/{did}/nan-uniforms"
            )
            if not resp.get("has_nan_uniforms"):
                continue
            for u in resp.get("nan_uniforms", []) or []:
                type_val = u.get("type")
                type_str = (
                    f"0x{type_val:X}" if isinstance(type_val, int) else str(type_val)
                )
                components = u.get("bad_components", [])
                findings.append(
                    Finding(
                        summary=(
                            f"draw call {did}: {u.get('name')} "
                            f"(type={type_str}), components {components}"
                        ),
                        detail={
                            "dc_id": did,
                            "name": u.get("name"),
                            "type": type_val,
                            "bad_components": components,
                        },
                    )
                )

        status = "warn" if findings else "ok"
        return CheckResult(name=self.name, status=status, findings=findings)
