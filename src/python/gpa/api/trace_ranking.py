"""Confidence ranking for ``gpa trace`` candidates (Phase 3).

The Phase-1 scanner writes candidates as ``{path, type, confidence}`` where
``confidence`` is a coarse "high" for non-trivial values and "low" for
trivial ones (0/1/""/true/false). This module re-scores and sorts
candidates at query time using two structural signals:

1. **Hop distance** — proxy for "closeness to the calling code". Counted
   as the number of ``.`` / ``[`` separators in the path minus one (the
   root itself is 0 hops). Fewer hops → stronger signal.
2. **Value rarity** — count how many distinct *paths* hold the observed
   value across the last N frames. Rare values (count == 1) upgrade to
   "high"; over-common values (count > 5) downgrade to "low".

Ranking order, stable sort: ``(confidence tier desc, hops asc, path_len asc)``.

Note: the ranker is intentionally framework-agnostic. Plugins that want
to elevate framework-specific paths should emit ``confidence: "high"``
from the scanner side; GPA core does not encode plugin-specific hints.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------

_TIER_ORDER = {"high": 0, "medium": 1, "low": 2}


def _hop_count(path: str) -> int:
    """Return the number of hops from the declared root.

    ``"foo"`` → 0 hops. ``"foo.bar.baz"`` → 2 hops. Bracket
    indexing (``foo[0].bar``) counts as a hop.
    """
    if not path:
        return 0
    # Normalise ``foo[0]`` → ``foo.0`` so we count `[` as a separator.
    norm = re.sub(r"\[[^\]]*\]", ".idx", path)
    return norm.count(".")


def _apply_rarity(
    base_tier: str,
    rarity_count: int,
) -> str:
    """Upgrade / downgrade *base_tier* based on how often the observed
    value appears across the recent corpus.

    - ``rarity_count == 1``  → upgrade one tier (low→medium, medium→high).
    - ``rarity_count > 5``   → downgrade one tier (high→medium, medium→low).
    - otherwise              → unchanged.
    """
    if rarity_count <= 1:
        if base_tier == "low":
            return "medium"
        if base_tier == "medium":
            return "high"
        return "high"
    if rarity_count > 5:
        if base_tier == "high":
            return "medium"
        if base_tier == "medium":
            return "low"
        return "low"
    return base_tier


# ----------------------------------------------------------------------
# Public API
# ----------------------------------------------------------------------

def rank_candidates(
    candidates: List[Dict[str, Any]],
    observed_value: Any = None,  # retained for future signature compatibility
    corpus: Optional[Dict[str, int]] = None,
) -> List[Dict[str, Any]]:
    """Rank *candidates* in place-friendly manner.

    Args:
        candidates: Each entry must have ``path``. Optional ``confidence``
            (defaults to ``"high"``) and ``type``.
        observed_value: The captured value being reverse-looked-up. Kept
            in the signature for forward-compatibility; currently only
            used to compute rarity from *corpus* when the caller hasn't
            precomputed it.
        corpus: Optional ``{path: count}`` or ``{"__count__": N}`` mapping
            describing how many distinct paths hold the observed value
            across recent frames. If *None* the rarity step is skipped.

    Returns:
        A new list, sorted ``(tier, hops, path length)``. Each entry is
        enriched with:

        - ``distance_hops`` — computed hop count
        - ``confidence`` — re-scored tier after rarity + hint bump
        - ``raw_confidence`` — the original scanner-provided tier
    """
    rarity_count: Optional[int] = None
    if corpus is not None:
        if "__count__" in corpus:
            rarity_count = int(corpus["__count__"])
        else:
            rarity_count = len(corpus)

    enriched: List[Dict[str, Any]] = []
    for c in candidates:
        if not isinstance(c, dict) or "path" not in c:
            continue
        path = str(c["path"])
        raw_tier = str(c.get("confidence", "high")).lower()
        if raw_tier not in _TIER_ORDER:
            raw_tier = "high"
        tier = raw_tier
        if rarity_count is not None:
            tier = _apply_rarity(tier, rarity_count)
        entry = dict(c)
        entry["distance_hops"] = _hop_count(path)
        entry["confidence"] = tier
        entry["raw_confidence"] = raw_tier
        enriched.append(entry)

    enriched.sort(
        key=lambda e: (
            _TIER_ORDER[e["confidence"]],
            e["distance_hops"],
            len(e["path"]),
        )
    )
    return enriched


def build_corpus_for_value(
    trace_store,
    value_hash: str,
    frame_ids: Iterable[int],
) -> Dict[str, int]:
    """Count distinct paths that hold *value_hash* across recent frames.

    Used to feed ``rank_candidates(..., corpus=...)``. Returns ``{"__count__": N}``
    so callers can treat the count opaquely.
    """
    seen_paths: set = set()
    for fid in frame_ids:
        hits = trace_store.find_value(fid, value_hash)
        for h in hits:
            p = h.get("path")
            if isinstance(p, str):
                seen_paths.add(p)
    return {"__count__": len(seen_paths)}
