# OpenGPA WebGL Shim — M6

WebGL interception via a Chromium browser extension + a Node.js WebSocket bridge.

## Architecture

```
Browser (page context)
  interceptor.js  ← monkey-patches WebGLRenderingContext / WebGL2RenderingContext
       |
       | WebSocket  ws://127.0.0.1:18081
       v
  Node.js bridge  (bridge.js)
       |
       | Unix domain socket  /tmp/gpa.sock
       v
  OpenGPA engine
```

The content script (`content.js`) injects `interceptor.js` into the page context at
`document_start` so the patches are in place before any WebGL context is created.

## Loading the Extension in Chrome

### Step 1: Navigate to Extensions Page
1. Open Chrome and go to `chrome://extensions`

### Step 2: Enable Developer Mode
- Toggle **Developer mode** in the top-right corner

### Step 3: Load Unpacked Extension
1. Click **Load unpacked**
2. Navigate to the OpenGPA repository and select `src/shims/webgl/extension/`
3. The extension will appear in your extensions list as "OpenGPA WebGL Debugger"

The extension patches all WebGL contexts in every tab automatically once loaded.

### Step 4: Verify Extension is Running
- You should see "OpenGPA WebGL Debugger (0.1.0)" in your extensions list
- Look for the extension icon in your toolbar (or in the extension menu)

## Starting the Bridge

The bridge is a Node.js service that relays WebGL interception data from the browser to the OpenGPA engine.

### Prerequisites
- Node.js 14+ installed
- WebSocket client (`ws` npm package)

### Setup and Start

```bash
cd src/shims/webgl/bridge
npm install
npm start
```

You should see output like:
```
Bridge listening on ws://127.0.0.1:18081
Bridge connected to IPC socket at /tmp/gpa.sock
```

**Important**: The bridge must be running **before** the OpenGPA engine (or at least before the first
WebGL frame is rendered in the browser).

## Environment Variables

| Variable          | Default          | Description                              |
|-------------------|------------------|------------------------------------------|
| `GPA_SOCKET_PATH` | `/tmp/gpa.sock`  | Unix socket path to the OpenGPA engine   |
| `GPA_WS_PORT`     | `18081`          | WebSocket port the bridge listens on     |

## Validation Status (as of 2026-04-16)

The following was verified with Node.js v20.19.5 / npm 10.8.2 on Linux:

| Component | Check | Result |
|---|---|---|
| `manifest.json` | Valid JSON + MV3 fields | PASS |
| `interceptor.js` | Node syntax check | PASS |
| `content.js` | Node syntax check | PASS |
| `background.js` | Node syntax check | PASS |
| `gpa-threejs-plugin.js` (copy of `clients/threejs/index.js`) | Node syntax check | PASS |
| `bridge/package.json` | `npm install` (`ws` dep) | PASS — 0 vulnerabilities |
| Bridge startup | `node bridge.js` | PASS — WebSocket server binds on `ws://127.0.0.1:18081` |
| Bridge engine connection | Unix socket connect | EXPECTED FAIL — engine not running; bridge retries every 3 s cleanly |

### What works end-to-end today

- The bridge starts, binds the WebSocket port, and enters a graceful
  reconnect loop when the engine socket is absent.
- All JS files are syntactically valid and structurally sound.
- The manifest is a valid Manifest V3 extension with correct `content_scripts`
  and `web_accessible_resources` sections.
- A minimal HTML test page is at `tests/integration/webgl_test.html`.  It
  renders a coloured triangle via WebGL1 and demonstrates the interception
  path: frame data is sent over WebSocket after each `requestAnimationFrame`
  tick if the bridge is running.

### What is needed for full E2E testing

1. **Chrome / Chromium** — the extension requires a real browser; there is no
   headless-WebGL runner available in this environment.  Options:
   - Use `puppeteer` with `--load-extension` flag in a CI image that has Chrome.
   - Use Playwright with `--channel chromium` and `launchPersistentContext`
     (supports loading extensions).
2. **Running OpenGPA engine** — the bridge forwards frame metadata to the engine
   over a Unix socket (`/tmp/gpa.sock` by default).  Without the engine the
   bridge operates in passthrough (log-only) mode.
3. **Shared-memory (SHM) native addon** — full pixel readback requires a native
   Node.js addon (`node-addon-api` + `shm_open`/`mmap`) or an inline
   variable-length socket message.  Planned for M6+.

## Known Limitations (v1)

- **No shared memory (SHM).** The bridge sends only frame metadata (frame ID +
  draw-call count) over the Unix socket. Full pixel data would require a native
  Node.js addon (`node-addon-api`) to call `shm_open`/`mmap`. Planned for a
  future milestone.
- **No `gl.readPixels` readback per frame.** Framebuffer readback is expensive;
  it will be triggered on demand by the engine, not automatically every frame.
- **Uniform tracking is a passthrough.** Uniform setter methods are patched but
  values are not stored in shadow state in v1.
- **Single shared state object.** All WebGL contexts in a page share the same
  `state` object. Multi-canvas pages may produce interleaved draw-call lists.
  Per-context state is a future improvement.
