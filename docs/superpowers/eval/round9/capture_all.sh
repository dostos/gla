#!/bin/bash
# Round 9 capture with GPA_TRACE_NATIVE + GPA_TRACE_NATIVE_STACK enabled.
set -u
cd /home/jingyulee/gh/gla
export DISPLAY=:99
export PATH=/home/jingyulee/gh/gla/bin:$PATH

eval "$(gpa env)"
echo "session: $GPA_SESSION port=$GPA_PORT"

probe_fid() {
  local start=$1
  local last=-1
  local i=$start
  while true; do
    local r
    r=$(curl -sH "Authorization: Bearer $GPA_TOKEN" "http://127.0.0.1:$GPA_PORT/api/v1/frames/$i/overview" 2>/dev/null)
    if echo "$r" | grep -q '"frame_id"'; then
      last=$i
      i=$((i+1))
    else
      break
    fi
  done
  echo $last
}

BEFORE=$(probe_fid 1)
echo "initial max fid: $BEFORE"

: > /tmp/eval_round9/captures.txt
for scen in $(cat /tmp/round9_scenarios.txt); do
  BIN="bazel-bin/tests/eval/$scen"
  if [ ! -x "$BIN" ]; then
    echo "$scen,ERROR_NOBIN,0,0,0" >> /tmp/eval_round9/captures.txt
    echo "[capture] $scen -> NO BIN"
    continue
  fi

  LOG=/tmp/eval_round9/capture_${scen}.log
  timeout 6 env \
    LD_PRELOAD=bazel-bin/src/shims/gl/libgpa_gl.so \
    GPA_SOCKET_PATH="$GPA_SOCKET_PATH" \
    GPA_SHM_NAME="$GPA_SHM_NAME" \
    GPA_TRACE_NATIVE=1 \
    GPA_TRACE_NATIVE_STACK=1 \
    DISPLAY=:99 \
    "$BIN" >"$LOG" 2>&1 || true

  sleep 0.5
  AFTER=$(probe_fid $((BEFORE+1)))
  if [ "$AFTER" = "-1" ]; then
    # Extract trace globals count for debug
    G=$(grep -oE 'scanned [0-9]+ modules?, [0-9]+ globals?' "$LOG" | tail -1 || echo "no-scan")
    echo "$scen,NOCAPTURE,0,0,0" >> /tmp/eval_round9/captures.txt
    echo "[capture] $scen -> NOCAPTURE ($G)"
    continue
  fi
  FID=$AFTER
  OV=$(curl -sH "Authorization: Bearer $GPA_TOKEN" http://127.0.0.1:$GPA_PORT/api/v1/frames/$FID/overview)
  DC=$(echo "$OV" | python3 -c "import json,sys;d=json.load(sys.stdin);print(d.get('draw_call_count',0))" 2>/dev/null)
  # Count globals + subprograms from trace log
  GLOBALS=$(grep -oE '[0-9]+ globals' "$LOG" | tail -1 | grep -oE '[0-9]+' || echo 0)
  SUBPS=$(grep -oE '[0-9]+ subprograms' "$LOG" | tail -1 | grep -oE '[0-9]+' || echo 0)
  echo "$scen,$FID,$DC,$GLOBALS,$SUBPS" >> /tmp/eval_round9/captures.txt
  echo "[capture] $scen -> frame=$FID draws=$DC globals=$GLOBALS subps=$SUBPS"
  BEFORE=$AFTER
done

echo "DONE"
cat /tmp/eval_round9/captures.txt
