#!/usr/bin/env bash
# round_runner_template.sh
#
# Reference template for per-round OpenGPA eval dispatchers (Round 9+).
# Validates the requested (scenarios x tiers x modes) matrix against a
# USD budget via `python -m gpa.eval.plan`, then dispatches one
# `claude -p --output-format stream-json --max-turns 40` per cell in
# parallel, capturing each transcript to
# /tmp/eval_round${ROUND_NUMBER}/<scenario>_<mode>_<tier>.jsonl.
#
# Per-round customization (prompt templates, scenario selection, extra
# env vars for the agent, post-processing) should happen in a thin
# wrapper that sources/copies this file. The model catalog lives in
# src/python/gpa/eval/models.py — do NOT hardcode model IDs here.
#
# Env inputs:
#   ROUND_NUMBER      required, integer identifier for this round
#   SCENARIOS_FILE    required, newline-delimited scenario names
#   TIERS             default: "haiku sonnet opus"
#   MODES             default: "code_only with_gpa"
#   MAX_BUDGET_USD    default: 150
#   BASELINE_PER_RUN  default: 0.50 (sonnet per-run USD from prior round)
#   PROMPT_FILE       optional, prompt template path (round wrapper supplies)
#   REPO_ROOT         default: git rev-parse output
#
# Flags:
#   -y    skip interactive confirmation

set -euo pipefail

AUTO_YES=0
while getopts ":y" opt; do
    case "$opt" in
        y) AUTO_YES=1 ;;
        *) echo "unknown flag: -$OPTARG" >&2; exit 64 ;;
    esac
done

: "${ROUND_NUMBER:?ROUND_NUMBER env var required}"
: "${SCENARIOS_FILE:?SCENARIOS_FILE env var required}"
TIERS="${TIERS:-haiku sonnet opus}"
MODES="${MODES:-code_only with_gpa}"
MAX_BUDGET_USD="${MAX_BUDGET_USD:-150}"
BASELINE_PER_RUN="${BASELINE_PER_RUN:-0.50}"
REPO_ROOT="${REPO_ROOT:-$(git rev-parse --show-toplevel)}"

if [[ ! -f "$SCENARIOS_FILE" ]]; then
    echo "scenarios file not found: $SCENARIOS_FILE" >&2
    exit 66
fi

mapfile -t SCENARIOS < <(grep -v '^[[:space:]]*\(#.*\)\?$' "$SCENARIOS_FILE")
if [[ ${#SCENARIOS[@]} -eq 0 ]]; then
    echo "no scenarios found in $SCENARIOS_FILE" >&2
    exit 65
fi

OUT_DIR="/tmp/eval_round${ROUND_NUMBER}"
mkdir -p "$OUT_DIR"

# --- Budget check --------------------------------------------------------
PLAN_JSON=$(
    PYTHONPATH="$REPO_ROOT/src/python" python -m gpa.eval.plan \
        --scenarios "${SCENARIOS[@]}" \
        --tiers $TIERS \
        --modes $MODES \
        --max-budget-usd "$MAX_BUDGET_USD" \
        --baseline-per-run "$BASELINE_PER_RUN"
) || PLAN_RC=$?
PLAN_RC="${PLAN_RC:-0}"

echo "=== Round ${ROUND_NUMBER} plan ===" >&2
echo "$PLAN_JSON" >&2

if [[ "$PLAN_RC" -ne 0 ]]; then
    echo >&2
    echo "ABORT: plan was pruned or exceeds budget (rc=$PLAN_RC)." >&2
    echo "       raise MAX_BUDGET_USD or shrink SCENARIOS_FILE/TIERS/MODES." >&2
    exit "$PLAN_RC"
fi

# --- Confirmation --------------------------------------------------------
if [[ "$AUTO_YES" -ne 1 ]]; then
    echo >&2
    read -rp "Proceed with dispatch? [y/N] " reply
    case "$reply" in
        y|Y|yes|YES) ;;
        *) echo "aborted." >&2; exit 1 ;;
    esac
fi

# --- Dispatch ------------------------------------------------------------
claude_id_for() {
    local tier="$1"
    PYTHONPATH="$REPO_ROOT/src/python" python -c \
        "from gpa.eval.models import claude_id; print(claude_id('$tier'))"
}

dispatch_one() {
    local scenario="$1" mode="$2" tier="$3"
    local model_id out
    model_id="$(claude_id_for "$tier")"
    out="$OUT_DIR/${scenario}_${mode}_${tier}.jsonl"

    local prompt_args=()
    if [[ -n "${PROMPT_FILE:-}" && -f "${PROMPT_FILE}" ]]; then
        prompt_args+=(-p "$(cat "$PROMPT_FILE")")
    else
        prompt_args+=(-p "Diagnose scenario=$scenario mode=$mode")
    fi

    echo "[dispatch] scenario=$scenario mode=$mode tier=$tier model=$model_id -> $out" >&2
    GPA_SCENARIO="$scenario" GPA_MODE="$mode" \
        claude "${prompt_args[@]}" \
            --output-format stream-json \
            --max-turns 40 \
            --model "$model_id" \
            >"$out" 2>&1 &
}

for scenario in "${SCENARIOS[@]}"; do
    for mode in $MODES; do
        for tier in $TIERS; do
            dispatch_one "$scenario" "$mode" "$tier"
        done
    done
done

wait
echo "=== Round ${ROUND_NUMBER} complete. Transcripts in $OUT_DIR ===" >&2
