#!/usr/bin/env bash
# p2_chromium_capture.sh — chromium-headless harness for Path 2 capture POC.
#
# Goal: launch a non-snap chromium under Xvfb with our LD_PRELOAD GL shim
# attached and a three.js page loaded, so the OpenGPA engine sees real
# WebGL frames captured via the desktop-GL (libGL.so) path.
#
# Status (2026-04-30): blocked. The shim *does* load into chromium's GPU
# process and libGL.so is present in /proc/$GPU/maps, but ANGLE resolves
# GL entrypoints via direct dlsym() against the libGL handle it dlopened —
# bypassing LD_PRELOAD interposition. Zero glXSwapBuffers / glClear /
# glDrawArrays calls hit our wrappers. See
# docs/superpowers/eval/round13/path2-chromium-harness.md for evidence.
#
# This script is preserved as-is so the harness can be re-run when a
# workaround is found (e.g. wrap libGL itself, or use a chromium build
# without ANGLE for desktop-GL).

set -euo pipefail

# --------- args ---------
HTML_PATH="${1:-/tmp/p2-index.html}"
ENGINE_PORT="${2:-18084}"
WAIT_SECONDS="${3:-12}"
PROFILE_ROOT="${PROFILE_ROOT:-/tmp/p2-chromium}"
LOG_DIR="${LOG_DIR:-/data3/p2-poc}"

mkdir -p "$LOG_DIR"
mkdir -p "$PROFILE_ROOT"
PROFILE_DIR="$(mktemp -d -p "$PROFILE_ROOT" prof-XXXXXX)"

# --------- locate the OpenGPA shim ---------
# bazel-bin symlink resolves to whichever bazel cache built it last.
# We resolve to a real file path so LD_PRELOAD survives chromium's
# zygote fork.
SHIM_REAL=$(find /home/jingyulee/.cache/bazel -name 'libgpa_gl.so' -path '*/src/shims/gl/*' 2>/dev/null | head -1)
if [[ -z "$SHIM_REAL" ]]; then
  echo "ERROR: libgpa_gl.so not found in bazel cache; build with 'bazel build //src/shims/gl/...' first" >&2
  exit 1
fi
# Copy to /tmp because some sandboxed chromium builds (snap) cannot read
# arbitrary $HOME paths but /tmp is always allowed.
SHIM=/tmp/libgpa_gl_p2.so
cp -f "$SHIM_REAL" "$SHIM"
chmod 0755 "$SHIM"

# --------- locate a non-snap chromium ---------
# Snap chromium strips LD_PRELOAD via snap-confine before exec'ing chrome,
# so we use the playwright-managed chromium or any other standalone
# chrome binary. Override CHROME_BIN to point at your own.
CHROME_BIN="${CHROME_BIN:-}"
if [[ -z "$CHROME_BIN" ]]; then
  for cand in \
    /home/jingyulee/.cache/ms-playwright/chromium-1208/chrome-linux64/chrome \
    /home/jingyulee/.cache/ms-playwright/chromium_headless_shell-1208/chrome-headless-shell-linux64/chrome-headless-shell \
    /home/jingyulee/opt/chromium/chrome-linux/chrome ; do
    [[ -x "$cand" ]] && CHROME_BIN="$cand" && break
  done
fi
if [[ -z "$CHROME_BIN" || ! -x "$CHROME_BIN" ]]; then
  echo "ERROR: no chromium binary found. Install via npx playwright install chromium or set CHROME_BIN" >&2
  exit 1
fi

# --------- ensure Xvfb is up ---------
if ! pgrep -f 'Xvfb :99' > /dev/null 2>&1; then
  echo "starting Xvfb :99 ..."
  Xvfb :99 -screen 0 800x600x24 > "$LOG_DIR/xvfb.log" 2>&1 &
  sleep 1
fi

# --------- copy HTML to /tmp (in case caller passed a $HOME path the
# chromium sandbox can't read) ---------
HTML_TMP=/tmp/p2-index.html
cp -f "$HTML_PATH" "$HTML_TMP"

# --------- baseline frame count ---------
FRAMES_BEFORE=$(curl -s "http://127.0.0.1:${ENGINE_PORT}/api/v1/frames" \
  | python3 -c 'import sys,json; print(json.load(sys.stdin).get("count","?"))' || echo "?")
echo "engine port=$ENGINE_PORT frames_before=$FRAMES_BEFORE"
echo "shim=$SHIM"
echo "chrome=$CHROME_BIN"
echo "profile=$PROFILE_DIR"
echo "html=$HTML_TMP"

# --------- launch chromium ---------
LOG="$LOG_DIR/chromium-$(date +%H%M%S).log"

# Flag rationale (each one matters):
#   --headless=new           : modern headless mode (legacy headless doesn't render WebGL).
#   --no-sandbox             : disable namespace sandbox (interferes with LD_PRELOAD propagation
#                              even when /usr/share/permissions allow it; combined with
#                              --disable-gpu-sandbox to also disable the GPU's separate sandbox).
#   --disable-gpu-sandbox    : same intent — keep LD_PRELOAD attached to the GPU child process.
#   --use-gl=angle --use-angle=gl
#                            : route WebGL through ANGLE's desktop-GL backend, which on Linux
#                              maps to libGLX.so / libGL.so. The only chromium combination
#                              that loads libGL.so into the GPU process; --use-gl=desktop is
#                              rejected by chromium's allow-list of GL implementations.
#   --enable-webgl           : explicit; safety belt against env opt-outs.
#   --ignore-gpu-blocklist   : without this, headless chromium blocklists WebGL in software-only
#                              configurations (e.g. when Vulkan probe fails on Mesa LLVMpipe).
#   --enable-unsafe-swiftshader
#                            : chromium 145+ requires this to permit non-blocklisted WebGL on
#                              CPU-only stacks; without it, three.js gets context_lost.
#   --window-size=400,300    : matches the canvas size in the HTML for a deterministic FB size.
#   --user-data-dir=...      : isolated profile so we don't trample on user state.
#   --enable-logging=stderr --v=1
#                            : surface ANGLE / GPU init errors into our log.
#
# Things deliberately NOT used after testing:
#   --no-zygote              : prevents chromium from spawning a separate GPU process at all
#                              (everything collapses into the browser process). This avoids the
#                              propagation problem but is incompatible with --headless=new in
#                              recent chromium and doesn't help — same ANGLE bypass applies.
#   --disable-features=Vulkan : doesn't actually disable the Vulkan probe in gpu_init.cc;
#                               the failed probe still triggers the WebGL blocklist branch.
#   --use-vulkan=disabled    : same.
#   --test-type              : forces chromium to exit early after dumping histograms before
#                               three.js can render.

LD_PRELOAD="$SHIM" \
GPA_SOCKET_PATH="${GPA_SOCKET_PATH:-/tmp/gpa_p2.sock}" \
GPA_SHM_NAME="${GPA_SHM_NAME:-/gpa_p2}" \
DISPLAY="${DISPLAY:-:99}" \
"$CHROME_BIN" \
  --headless=new \
  --no-sandbox \
  --disable-gpu-sandbox \
  --use-gl=angle --use-angle=gl \
  --enable-webgl \
  --ignore-gpu-blocklist \
  --enable-unsafe-swiftshader \
  --window-size=400,300 \
  --user-data-dir="$PROFILE_DIR" \
  --enable-logging=stderr --v=1 \
  "file://$HTML_TMP" \
  > "$LOG" 2>&1 &

CHROME_PID=$!
echo "chromium pid=$CHROME_PID  log=$LOG"

# --------- wait for the page to render and self-close (or timeout) ---------
sleep "$WAIT_SECONDS"

# --------- snapshot GPU process (for diagnostics) ---------
GPU_PID=$(ps -ef | awk -v p="$PROFILE_DIR" \
  '$0 ~ "--type=gpu-process" && $0 ~ p { print $2; exit }')
if [[ -n "$GPU_PID" && -d "/proc/$GPU_PID" ]]; then
  echo "=== gpu-process ($GPU_PID) maps (filtered) ===" | tee -a "$LOG"
  grep -E 'libGL\.|libEGL\.|libGLX|libGLES|libgpa_gl|swiftshader|libvulkan' "/proc/$GPU_PID/maps" 2>/dev/null \
    | awk '{print $NF}' | sort -u | tee -a "$LOG"
fi

# --------- kill chromium tree ---------
pkill -f "user-data-dir=$PROFILE_DIR" 2>/dev/null || true
sleep 1

FRAMES_AFTER=$(curl -s "http://127.0.0.1:${ENGINE_PORT}/api/v1/frames" \
  | python3 -c 'import sys,json; print(json.load(sys.stdin).get("count","?"))' || echo "?")

echo
echo "================================================="
echo "frames_before = $FRAMES_BEFORE"
echo "frames_after  = $FRAMES_AFTER"
echo "log           = $LOG"
echo "================================================="
