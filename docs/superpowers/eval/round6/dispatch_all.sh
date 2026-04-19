#!/bin/bash
# Dispatch all 80 Round 6 eval runs in parallel.
set -u
cd /home/jingyulee/gh/gla
export PATH=/home/jingyulee/gh/gla/bin:$PATH
export GPA_PYTHON=/home/jingyulee/.cache/bazel/_bazel_jingyulee/97df310dd69562eef617a1c4f9fefa27/external/rules_python~~python~python_3_11_x86_64-unknown-linux-gnu/bin/python3.11

LOG=/tmp/eval_round6/dispatch.log
: > "$LOG"

while IFS=',' read -r scen fid dc; do
  [ -z "$scen" ] && continue
  [ "$fid" = "ERROR_NOBIN" ] && continue
  [ "$fid" = "NOCAPTURE" ] && continue
  for mode in code_only with_gpa; do
    for model in haiku sonnet; do
      DLOG=/tmp/eval_round6/dispatch_${scen}_${mode}_${model}.log
      (
        bash /tmp/eval_round6/run_subagent.sh "$scen" "$mode" "$model" "$fid" \
          > "$DLOG" 2>&1
        echo "done $scen $mode $model" >> "$LOG"
      ) &
    done
  done
done < /tmp/eval_round6/captures.txt

wait
echo "ALL DONE" >> "$LOG"
