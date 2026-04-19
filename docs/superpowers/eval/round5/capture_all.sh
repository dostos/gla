#!/bin/bash
# Capture frames for all R5 scenarios sequentially.
# Output: /tmp/eval_round5/captures.txt with "<scenario>,<frame_id>,<draws>" lines
set -u
cd /home/jingyulee/gh/gla
export DISPLAY=:99

: > /tmp/eval_round5/captures.txt

for scen in $(cat /tmp/round5_scenarios.txt); do
  BIN="bazel-bin/tests/eval/$scen"
  if [ ! -x "$BIN" ]; then
    echo "$scen,ERROR_NOBIN,0" >> /tmp/eval_round5/captures.txt
    continue
  fi

  # Run binary briefly under LD_PRELOAD with a timeout (many scenarios may be infinite loops)
  LOG=/tmp/eval_round5/capture_${scen}.log
  timeout 4 env \
    LD_PRELOAD=bazel-bin/src/shims/gl/libgpa_gl.so \
    GPA_SOCKET_PATH=/tmp/gpa_eval.sock \
    GPA_SHM_NAME=/gpa_eval \
    DISPLAY=:99 \
    "$BIN" >"$LOG" 2>&1 || true

  sleep 0.3
  # Query current frame
  OV=$(curl -sH 'Authorization: Bearer EVALTOKEN' http://127.0.0.1:18080/api/v1/frames/current/overview)
  FID=$(echo "$OV" | python3 -c "import json,sys;d=json.load(sys.stdin);print(d.get('frame_id',-1))" 2>/dev/null)
  DC=$(echo "$OV" | python3 -c "import json,sys;d=json.load(sys.stdin);print(d.get('draw_call_count',0))" 2>/dev/null)
  echo "$scen,$FID,$DC" >> /tmp/eval_round5/captures.txt
  echo "[capture] $scen -> frame=$FID draws=$DC"
done
