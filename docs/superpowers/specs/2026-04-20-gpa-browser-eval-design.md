# `gpa-browser` — Browser-Based Eval for Source-Logical Bugs

**Date:** 2026-04-20
**Status:** design; not yet implemented
**Motivation:** `gpa trace` (Phases 1–3 shipped) reflects into JS globals to reverse-lookup app-level fields. The existing eval harness runs minimal C repros under `LD_PRELOAD` — no JS state → trace never has anything to find. To measure whether `gpa trace` closes the R5–R8 "0/4 source-logical" gap, we need scenarios that execute real framework code in a real browser. This spec pins the MVP.

## Goals

- **Run real three.js / mapbox-gl-js / PIXI pages** as eval scenarios in headless Chromium.
- **Load the WebGL extension** so the scanner + interceptor capture live state.
- **Reuse the existing eval harness** (scoring, verdict classifier, stream-json telemetry) without rewriting it.
- **Pilot with 3 scenarios.** If measurable, grow the set. If not, the spec gets recorded and we move on.
- **Xvfb-friendly.** No headed dependency; CI / SSH-box usable.

## Non-goals

- Converting all 45 existing C-repro scenarios. Too much work; the C repros stay where they are — they're the state-collision ground truth.
- A general-purpose browser automation framework. Puppeteer-level scope only; no Selenium, no cross-browser.
- Production scaling. MVP targets one-at-a-time scenario execution.

## Pilot scenarios (first 3)

Chosen from the 15 source-logical scenarios just mined (`631b4de`) based on which have the cleanest browser reproducibility:

1. **r21_tile_id_5_bit_stencil_overflow** (mapbox-gl-js, large zoom levels wrap the stencil mask) — direct r27 analog
2. **r10_polygon_rendered_from_dynamic_geojson_so** (mapbox-gl-js, dynamic GeoJSON source tile-boundary) — real JS state flows
3. **r14_cannot_override_vertexnode_of_instanced_** (three.js r182 InstancedMesh + vertexNode override, NodeMaterial)

Each is simple enough to fit in a single HTML page + one npm-cached framework bundle.

## Architecture

```
+-------------------------------+          +-----------------+
| Headless Chromium (xvfb)      | ←─────→  | gpa engine      |
|  + webgl extension (loaded)   |  :18080  | (FastAPI)       |
|  + scenario page              |          |                 |
|    <script src=".../map.js">  |          | /frames/*/...   |
|    window.map = ...           |          | /sources (POST) |
|    triggerBug()               |          +-----------------+
+-------------------------------+
              ^
              │ chromium --headless=new
              │         --load-extension=...
              │         --disable-gpu=no (software WebGL via swiftshader)
              │         http://localhost:8765/r21/
              │
    +----------------------+
    |  python -m gpa.       |
    |  browser.runner      |
    |  (serves scenarios,  |
    |   launches browser,  |
    |   waits for frames)  |
    +----------------------+
```

- **Static server** serves scenario HTML + pinned framework bundles from `tests/eval-browser/`
- **Python browser runner** spawns Chromium, waits for captured frames in `TraceStore`, tears down on exit
- **Extension** already built in `src/shims/webgl/extension/` (has `gpa-trace.js` + `interceptor.js`)

## Scenario file layout

```
tests/eval-browser/
├── r21_tile_id_overflow/
│   ├── index.html                 # loads mapbox-gl-js + triggers the bug
│   ├── scenario.md                # User Report + Ground Truth + Framework + Upstream Snapshot
│   ├── assets/
│   │   └── style.json             # mapbox style w/ the triggering config
│   └── framework/                 # pinned framework build at pre-fix SHA
│       └── mapbox-gl-js.2.15.0.js
├── r10_polygon_geojson/
│   └── ...
└── r14_vertexnode_override/
    └── ...
```

- `index.html` self-triggers the bug on load — renders ~30 frames then posts `window.__gpa_done = true` so the runner knows to tear down.
- `scenario.md` uses the same format as C repros (User Report / Ground Truth / Tier / Framework / etc.) — the eval harness already parses this.
- `framework/` contains a pinned bundle so scenarios are reproducible years from now. Licensed libs (MIT/BSD) only; document the license per scenario.

## Command surface

### `gpa run-browser [--scenario NAME] [--timeout SEC] [--session DIR]`

New CLI subcommand mirroring `gpa run`:

1. Start engine (same as `gpa run` today — embedded lifecycle)
2. Start a lightweight static server on an ephemeral port serving `tests/eval-browser/`
3. Launch Chromium headless with:
   - `--load-extension=$(readlink -f src/shims/webgl/extension)`
   - `--disable-gpu-sandbox`
   - `--enable-unsafe-swiftshader` (software WebGL for Xvfb)
   - URL pointing at `http://localhost:<port>/<scenario>/index.html`
4. Poll `TraceStore` + `/frames/latest/overview` until `window.__gpa_done` equivalent (a sentinel in the trace annotations) or timeout
5. Terminate Chromium; tear down engine (unless daemon mode)
6. Print session + frame count, exit 0

Flags:
- `--scenario NAME` — pick from `tests/eval-browser/*`
- `--timeout SEC` — default 30
- `--chromium-path PATH` — override chromium binary (default: autodetect `chromium` / `google-chrome`)
- `--keep-open` — don't kill Chromium on finish (for interactive debugging)

### Extension config

The extension needs a way to target the local engine. Currently hardcoded in `gpa-trace.js` to `http://127.0.0.1:18080`. Add env/localStorage injection during scenario boot:

```html
<script>
  localStorage.GPA_TRACE_MODE = 'gated';
  localStorage.GPA_TRACE_ENDPOINT = 'http://127.0.0.1:18080/api/v1';
  localStorage.GPA_TRACE_TOKEN = '<injected-by-runner>';
</script>
```

The runner injects the token into the scenario page via a query-string (`?token=XXX`) that the page reads and sets on localStorage before the framework loads.

## Eval harness integration

`tests/eval-browser/<scenario>/scenario.md` uses the existing format. The harness detects browser-mode scenarios by the presence of `index.html` + `framework/` (vs a `main.c`). Runner dispatches to `gpa run-browser` instead of `gpa run`.

Models: Haiku + Sonnet + Opus. Each gets the same user-report prompt. Tools include `gpa trace *` (which is the point of this whole thing).

Success criteria for R9 browser subset:
- `gpa trace` is invoked ≥ 1×/run on with_gpa runs
- At least 1/3 of the pilot scenarios go from "0/4 unsolvable" (historical for similar C repros) to "solved by at least one model" with trace data
- Capture overhead ≤ 500 ms per frame (browsers are slow anyway; relaxed vs C-shim)

## Implementation phases

### Phase 1 — MVP runner (2–3 days)
- `src/python/gpa/browser/runner.py` — Chromium launcher, port allocation, static server
- `src/python/gpa/cli/commands/run_browser.py` — CLI subcommand
- First pilot scenario: `tests/eval-browser/r21_tile_id_overflow/` end-to-end
- Tests: smoke test that runner launches Chromium + captures ≥ 1 frame into `TraceStore`

### Phase 2 — Remaining pilot scenarios + harness wiring (1–2 days)
- `tests/eval-browser/r10_polygon_geojson/`
- `tests/eval-browser/r14_vertexnode_override/`
- Harness recognizes browser-mode scenarios; dispatches `gpa run-browser`

### Phase 3 — Round 9 eval (same session as everything else)
- Budget planner accounts for browser-scenario runs (slower → add ~1.5× multiplier)
- Round 9 runs both C-repro and browser subsets; compared in the report

### Phase 4 — Post-R9 growth (conditional)
- If R9 shows measurable trace lift: grow the set (5–10 more browser scenarios)
- If not: park the browser-eval track, document why, move on

## Open questions

1. **Chromium install** — assume user has chromium/google-chrome. Fail gracefully with install instructions if not. Use `which chromium || which google-chrome` autodetect.
2. **Framework bundle licensing** — MIT/BSD fine; document per scenario. Avoid copying anything GPL.
3. **swiftshader vs real GL** — Xvfb + swiftshader is easy but slow; real GL via Xvfb's glx would be faster but fragile. Default swiftshader; document how to swap.
4. **Scenario sentinel** — `window.__gpa_done = true` + annotation POST is the simplest completion signal. Consider a timeout floor (5s minimum) even if the scenario claims done, so short pages still capture meaningful state.
5. **What if `gpa trace` finds nothing in the scenario?** — would mean reflection isn't reaching the relevant state. In that case, the scenario's HTML can `gpa.trace.addRoot(suspectObject)` manually. We won't hide this from scenario authors; it's part of the debugging story.

## Non-feature: full Puppeteer / Playwright

Chromium + CLI flags is enough for the MVP. Puppeteer adds Node dependency, another version matrix, and is overkill for "launch page, wait, kill" flows. Revisit if scenarios need script-driven interaction (clicks, drags) that static HTML can't do.
