"""``GET /api/v1/frames/{frame_id}/check-config`` endpoint.

Cross-validates captured GL state against a small library of
hand-curated framework-config rules. Read-only. Idempotent. Backed by
:class:`gpa.checks.RuleEngine`.

Response shape (per spec §3.2):

    {
      "frame_id": int,
      "rules_evaluated": [str, ...],
      "findings": [
        {
          "rule_id": str,
          "severity": "error|warn|info",
          "message": str,
          "hint": str,
          "evidence": {...}
        },
        ...
      ]
    }
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, Dict, List, Optional, Union

from fastapi import APIRouter, HTTPException, Query, Request

from gpa.api.app import resolve_frame_id, safe_json_response
from gpa.checks import default_engine

router = APIRouter(tags=["check-config"])


def build_gl_state(provider, frame_id: int) -> Optional[Dict[str, Any]]:
    """Build the dict that rules consume.

    Returns ``None`` if the frame does not exist on the provider.
    """
    overview = provider.get_frame_overview(frame_id)
    if overview is None:
        return None
    # Deliberately fetch a generous page; check-config rules look at the
    # whole frame. Capture sizes >500 draw calls per frame are rare; if
    # they do happen, the rule layer still runs but with a truncated view.
    drawcalls = provider.list_draw_calls(frame_id, limit=500, offset=0)
    return {
        "frame_id": int(frame_id),
        "overview": asdict(overview),
        "drawcalls": [asdict(dc) for dc in drawcalls],
    }


@router.get("/frames/{frame_id}/check-config")
def get_check_config(
    frame_id: Union[int, str],
    request: Request,
    rule: Optional[List[str]] = Query(None),
    severity: str = Query("warn"),
):
    if severity not in {"error", "warn", "info"}:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Invalid severity {severity!r}; must be one of "
                "'error', 'warn', 'info'."
            ),
        )

    provider = request.app.state.provider
    frame_id = resolve_frame_id(frame_id, provider)

    engine = default_engine()
    known_ids = set(engine.rule_ids())
    requested_ids: Optional[List[str]] = None
    if rule:
        # Flatten comma-separated values too — clients sometimes pass
        # ?rule=a,b in addition to ?rule=a&rule=b.
        flat: List[str] = []
        for r in rule:
            for piece in r.split(","):
                piece = piece.strip()
                if piece:
                    flat.append(piece)
        unknown = [r for r in flat if r not in known_ids]
        if unknown:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Unknown rule id(s): {sorted(set(unknown))}. "
                    f"Known: {sorted(known_ids)}"
                ),
            )
        requested_ids = flat

    state = build_gl_state(provider, frame_id)
    if state is None:
        raise HTTPException(
            status_code=404,
            detail=f"Frame {frame_id} not found",
        )

    findings = engine.run(
        state, rule_ids=requested_ids, min_severity=severity
    )
    rules_evaluated = engine.evaluated_rule_ids(rule_ids=requested_ids)

    return safe_json_response({
        "frame_id": int(frame_id),
        "rules_evaluated": rules_evaluated,
        "findings": [f.to_dict() for f in findings],
    })


@router.get("/check-config/rules")
def list_rules(request: Request):
    """List all known rules — used by ``gpa check-config --rules``.

    Returns ``[{id, severity, message, hint, default_enabled}, ...]``.
    No frame data needed; useful as a smoke test for the engine.
    """
    engine = default_engine()
    rules = []
    for r in engine.all_rules():
        rules.append({
            "id": r.id,
            "severity": r.severity,
            "message": r.message_template,
            "hint": r.hint,
            "default_enabled": r.enabled_by_default,
        })
    return safe_json_response({"rules": rules})
