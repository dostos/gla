#!/bin/bash
# Capture frames for Round 6 using the new gpa session.
set -u
cd /home/jingyulee/gh/gla
export DISPLAY=:99
export PATH=/home/jingyulee/gh/gla/bin:$PATH
export GPA_PYTHON=/home/jingyulee/.cache/bazel/_bazel_jingyulee/97df310dd69562eef617a1c4f9fefa27/external/rules_python~~python~python_3_11_x86_64-unknown-linux-gnu/bin/python3.11

# Source the active session env
eval "$(gpa env)"

: > /tmp/eval_round6/captures.txt
echo "session: $GPA_SESSION port=$GPA_PORT token=$GPA_TOKEN"

for scen in $(cat /tmp/round5_scenarios.txt); do
  BIN="bazel-bin/tests/eval/$scen"
  if [ ! -x "$BIN" ]; then
    echo "$scen,ERROR_NOBIN,0" >> /tmp/eval_round6/captures.txt
    continue
  fi

  LOG=/tmp/eval_round6/capture_${scen}.log
  timeout 4 env \
    LD_PRELOAD=bazel-bin/src/shims/gl/libgpa_gl.so \
    GPA_SOCKET_PATH="$GPA_SOCKET_PATH" \
    GPA_SHM_NAME="$GPA_SHM_NAME" \
    DISPLAY=:99 \
    "$BIN" >"$LOG" 2>&1 || true

  sleep 0.3
  OV=$(curl -sH "Authorization: Bearer $GPA_TOKEN" http://127.0.0.1:$GPA_PORT/api/v1/frames/current/overview)
  FID=$(echo "$OV" | python3 -c "import json,sys;d=json.load(sys.stdin);print(d.get('frame_id',-1))" 2>/dev/null)
  DC=$(echo "$OV" | python3 -c "import json,sys;d=json.load(sys.stdin);print(d.get('draw_call_count',0))" 2>/dev/null)
  echo "$scen,$FID,$DC" >> /tmp/eval_round6/captures.txt
  echo "[capture] $scen -> frame=$FID draws=$DC"
done
