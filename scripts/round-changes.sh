#!/usr/bin/env bash
# Round-changes: enumerate commits that touched the OpenGPA system vs.
# the eval pipeline between two round-tags.
#
# Usage:
#   scripts/round-changes.sh <since-ref> [until-ref]
#
# Examples:
#   scripts/round-changes.sh round-r12b round-r12c
#   scripts/round-changes.sh round-r12c             # implies HEAD
#   scripts/round-changes.sh 11bc833 ad0af3e        # SHAs work too
#
# Output is two markdown sections — paste straight into the round log.
#
# Convention: tag a round at launch with `git tag round-<name> <sha>`.
# That gives a stable reproduction point. Without tags, fall back to
# SHAs / dates.

set -euo pipefail

if [[ $# -lt 1 || $# -gt 2 ]]; then
  echo "usage: $0 <since-ref> [until-ref]" >&2
  exit 2
fi

since="$1"
until="${2:-HEAD}"

# Path patterns. SYSTEM = OpenGPA the product (shims, engine, API, MCP,
# bindings, backends, framework integration). EVAL = the harness +
# scoring + mining + scenarios + prompts. Anything not matching either
# (docs, scripts, root configs) is "other" and reported separately.
SYSTEM_PATHS=(
  "src/shims/"
  "src/core/"
  "src/bindings/"
  "src/python/gpa/api/"
  "src/python/gpa/backends/"
  "src/python/gpa/mcp/"
  "src/python/gpa/framework/"
  "src/python/gpa/launcher.py"
  "src/python/gpa/cli/"
)
EVAL_PATHS=(
  "src/python/gpa/eval/"
  "tests/eval/"
  "tests/unit/python/test_eval"
  "tests/unit/python/test_curation"
  "tests/unit/python/test_scenario"
  "tests/unit/python/test_scope_hint.py"
  "tests/unit/python/test_scorer"
  "tests/unit/python/test_browser_tier"
  "tests/unit/python/test_harness"
  "tests/unit/python/test_cli_agent.py"
)

# Print a section: header + commits whose modified files match any path.
# `git log -- <paths>` filters commits to those touching at least one
# matching file. Empty list → no section emitted.
print_section() {
  local title="$1"; shift
  local paths=("$@")
  local out
  out="$(git log --no-merges --pretty='format:- `%h` %s' \
         "${since}..${until}" -- "${paths[@]}" 2>/dev/null)"
  if [[ -z "$out" ]]; then
    return 0
  fi
  echo "### $title"
  echo
  echo "$out"
  echo
}

echo "## Changes since \`$since\` (to \`$until\`)"
echo

print_section "System (OpenGPA itself)" "${SYSTEM_PATHS[@]}"
print_section "Eval pipeline" "${EVAL_PATHS[@]}"

# Other changes: subtract system+eval matched commits from total.
all_shas="$(git log --no-merges --pretty='%H' "${since}..${until}" || true)"
matched="$(git log --no-merges --pretty='%H' "${since}..${until}" \
           -- "${SYSTEM_PATHS[@]}" "${EVAL_PATHS[@]}" 2>/dev/null || true)"

if [[ -n "$all_shas" ]]; then
  unmatched="$(comm -23 <(echo "$all_shas" | sort) <(echo "$matched" | sort) || true)"
  if [[ -n "$unmatched" ]]; then
    echo "### Other (docs, scripts, configs)"
    echo
    while IFS= read -r sha; do
      [[ -z "$sha" ]] && continue
      git log --no-merges --pretty='format:- `%h` %s' "$sha" -1
      echo
    done <<<"$unmatched"
    echo
  fi
fi

# Quick file-touch summary for the system bucket — useful when reviewing
# whether a system commit is shim-side, engine-side, or API-side.
sys_files="$(git log --no-merges --name-only --pretty='format:' \
             "${since}..${until}" -- "${SYSTEM_PATHS[@]}" 2>/dev/null \
             | grep -v '^$' | sort -u || true)"
if [[ -n "$sys_files" ]]; then
  echo "### System files touched (deduped)"
  echo
  echo '```'
  echo "$sys_files"
  echo '```'
fi
