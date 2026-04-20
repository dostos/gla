# `gpa run-browser` — usage

Phase 1 MVP of the browser-based eval runner. Launches Chromium with the
WebGL extension loaded, serves a scenario HTML page on an ephemeral port,
and polls the engine for captured frames + `sources` payloads.

## Install chromium

```bash
# Debian / Ubuntu
sudo apt install chromium-browser

# or, on systems that ship google-chrome:
sudo apt install google-chrome-stable
```

Autodetection order: `chromium` → `chromium-browser` → `google-chrome`.
Override with `--chromium-path /path/to/chrome`.

## Run the pilot scenario

```bash
# Build shims + engine
bazel build //...

# With Xvfb (headless SSH box):
Xvfb :99 -screen 0 800x600x24 &
export DISPLAY=:99

# Invoke
PYTHONPATH=src/python python3 -m gpa.cli.main \
    run-browser --scenario r21_tile_id_overflow --timeout 10
```

Expected output:

```
[gpa] session /tmp/gpa-session-...
[gpa] scenario=r21_tile_id_overflow frames=1 sources=1 gpa_done=True timed_out=False duration=1.1s
```

Exit code 0. If Chromium isn't installed, exit 5 with a clear message.
Timeout with zero frames → exit 4.

## Flags

- `--scenario NAME` (required) — directory name under `tests/eval-browser/`.
- `--timeout SEC` — seconds to wait for capture completion. Default 30.
- `--chromium-path PATH` — override the chromium binary.
- `--keep-open` — do not kill Chromium on finish (interactive debugging).
- `--session DIR` — reuse a pre-started session (`gpa start`) instead of
  spawning a fresh one.
- `--port PORT` — REST port when creating a fresh session. Default 18080.

## Exit codes

| Code | Meaning |
|------|---------|
| 0    | Clean run — frames captured and/or `__gpa_done` sentinel set |
| 1    | Generic error (scenario missing, no index.html, engine failure) |
| 2    | `--session DIR` doesn't point at a valid session |
| 4    | Timed out with zero frames captured |
| 5    | Chromium binary not found |

## Troubleshooting

**Chromium exits immediately with no frames.**
Most common on Linux: missing `--no-sandbox`-compatible environment or no
GPU fallback. The runner already passes `--enable-unsafe-swiftshader` and
`--no-sandbox`, but some distros also need a writable `/tmp/chromium`
cache. Pass `--chromium-path $(which chromium) --keep-open` and inspect
stderr from the Popen.

**Scenario page can't reach the engine.**
Confirm the engine is on `127.0.0.1:<port>` and the session token matches:

```bash
cat $(readlink /tmp/gpa-session-current)/token
```

The scenario HTML reads `?token=XXX&port=YYY` from its URL and sticks
them into `localStorage` before the extension touches anything.

## Phase 2 preview

Phase 2 replaces the synthetic `fetch(sources)` in
`tests/eval-browser/r21_tile_id_overflow/index.html` with a real
`mapbox-gl-js` bundle pinned at a pre-fix SHA. The WebGL interceptor
produces the `sources` payload automatically; the scenario body just
drives `map.zoomTo(34)` and lets the stencil-tile-id bug reproduce.
