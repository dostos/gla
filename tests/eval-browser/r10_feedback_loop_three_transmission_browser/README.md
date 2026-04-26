# r10_feedback_loop_three_transmission_browser

Phase 2 of the OpenGPA browser eval — the first scenario that actually
loads a real framework (three.js, pre-fix SHA) and exercises
`gpa.trace.addRoot()` against framework objects.

See `scenario.md` for the bug write-up. This README is just operator
notes: how to run the scenario locally and what the bundle is.

## Run

```bash
# Headless capture via the OpenGPA CLI:
PATH=$PWD/bin:$PATH DISPLAY=:99 gpa run-browser \
    --scenario r10_feedback_loop_three_transmission_browser \
    --chromium-path ~/opt/chromium/chrome-linux/chrome \
    --timeout 30
```

Expected output (frames + sources non-zero, no timeout):

```
[gpa] scenario=r10_feedback_loop_three_transmission_browser \
      frames=N sources=M gpa_done=True timed_out=False ...
```

To view what the JS scanner posted:

```bash
TOKEN="$(cat $SESSION/token)"; PORT="$(cat $SESSION/port)"
curl -s -H "Authorization: Bearer $TOKEN" \
    "http://127.0.0.1:$PORT/api/v1/frames/0/drawcalls/0/sources" | jq .

# Reverse-lookup the transmission value:
curl -s -H "Authorization: Bearer $TOKEN" \
    "http://127.0.0.1:$PORT/api/v1/frames/0/trace/value?query=0.875" | jq .
```

## Manual repro (non-OpenGPA)

```bash
# Serve the scenario dir and open it in a normal browser:
cd tests/eval-browser/r10_feedback_loop_three_transmission_browser
python3 -m http.server 8000
# Open http://localhost:8000/index.html in Chrome with the OpenGPA
# extension loaded (or just to inspect the GL warnings in DevTools).
```

The "broken" symptom is that the back-side of the glass sphere does
not composite — DevTools shows
`GL_INVALID_OPERATION: Feedback loop formed between Framebuffer and
active Texture` — on any backend lacking
`WEBGL_multisampled_render_to_texture` (e.g. SwiftShader, the headless
Chromium default).

## Bundle attribution

`framework/three.module.min.js` + `framework/three.core.min.js` are
vendored verbatim from
<https://github.com/mrdoob/three.js> at SHA
`c2c5685879290d304c226a493061f6461021864c` (the pre-fix tree for issue
#33060). Upstream license: MIT, copied to `framework/LICENSE.three.js`.
See `framework/SOURCE.txt` for full attribution.

The fix landed in PR #33063 — see `scenario.md` `## Fix`.
