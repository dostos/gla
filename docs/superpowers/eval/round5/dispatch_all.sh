#!/bin/bash
# Dispatch all 80 R5 subagents in parallel.
# Reads /tmp/eval_round5/captures.txt; skips with_gpa for scenarios marked NOCAPTURE.
set -u
cd /tmp/eval_round5

PIDS=()
while IFS=, read -r scen fid draws; do
  [ -z "$scen" ] && continue
  for model in haiku sonnet; do
    # code_only always runs
    out=/tmp/eval_round5/${scen}_code_only_${model}.json
    if [ ! -s "$out" ]; then
      MAX_TURNS=40 ./run_subagent.sh "$scen" code_only "$model" 0 \
        >/tmp/eval_round5/dispatch_${scen}_code_only_${model}.log 2>&1 &
      PIDS+=($!)
    fi
    # with_gpa only if we have a frame
    if [ "$fid" != "NOCAPTURE" ] && [ "$fid" != "ERROR_NOBIN" ]; then
      out=/tmp/eval_round5/${scen}_with_gpa_${model}.json
      if [ ! -s "$out" ]; then
        MAX_TURNS=40 ./run_subagent.sh "$scen" with_gpa "$model" "$fid" \
          >/tmp/eval_round5/dispatch_${scen}_with_gpa_${model}.log 2>&1 &
        PIDS+=($!)
      fi
    fi
  done
done < /tmp/eval_round5/captures.txt

echo "Dispatched ${#PIDS[@]} subagents"
for p in "${PIDS[@]}"; do wait "$p"; done
echo "All done"
