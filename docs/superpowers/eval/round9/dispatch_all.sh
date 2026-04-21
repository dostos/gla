#!/bin/bash
# Round 9 parallel dispatcher
set -u
cd /tmp/eval_round9
: > dispatch_log.txt

N=0
while read -r scen mode model fid; do
  # Skip if already exists (for resumes)
  OUT="/tmp/eval_round9/${scen}_${mode}_${model}.jsonl"
  if [ -s "$OUT" ]; then
    # Check if valid final result
    if tail -1 "$OUT" | grep -q '"type":"result"'; then
      echo "[skip-done] $scen $mode $model"
      continue
    fi
  fi
  (
    bash /tmp/eval_round9/run_subagent.sh "$scen" "$mode" "$model" "$fid" > /dev/null 2>&1
    echo "[done] $scen $mode $model" >> /tmp/eval_round9/dispatch_log.txt
  ) &
  N=$((N+1))
done < /tmp/eval_round9/tasks.txt
echo "Dispatched $N runs, waiting..."
wait
echo "All done."
