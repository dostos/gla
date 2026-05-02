# OpenGPA CLI — Agent Integration

This document describes how an LLM agent (claude-cli, codex-cli, or any
shell-equipped agent) interacts with OpenGPA via the `gpa` CLI.

## When to use

When debugging an OpenGPA-captured graphics scenario. The eval harness
sets up a captured frame and points the agent at it via env vars; the
agent uses `gpa` shell calls to inspect the frame.

## Auth and environment

The eval harness pre-sets these env vars:

- `GPA_BASE_URL` — REST API endpoint (default `http://127.0.0.1:18080`)
- `GPA_TOKEN`    — bearer token (set by the engine's `gpa start`)
- `GPA_FRAME_ID` — pinned frame for this scenario (so `--frame` is automatic)
- `GPA_SOURCE_ROOT`   — root for `gpa source read|grep`
- `GPA_UPSTREAM_ROOT` — root for `gpa upstream read|list|grep`

## Frame workflow

```bash
gpa frames overview              # current frame summary (uses GPA_FRAME_ID)
gpa frames list --json           # all captured frame ids
gpa frames check-config          # run config-rule checks on the frame
```

## Drawcall workflow

```bash
gpa drawcalls list                       # all draw calls in the frame
gpa drawcalls explain --dc 47            # deep dive on draw 47
gpa drawcalls shader --dc 47             # shader source + state
gpa drawcalls textures --dc 47           # bound textures
gpa drawcalls vertices --dc 47           # vertex inputs + decoded data
gpa drawcalls diff --a 11 --b 12         # what changed between draws
gpa drawcalls nan-uniforms --dc 47       # uniforms with NaN values
gpa drawcalls feedback-loops --dc 47     # texture/framebuffer feedback issues
```

## Pixel and scene workflow

```bash
gpa pixel get --x 400 --y 300            # color/depth/stencil at a pixel
gpa pixel explain --x 400 --y 300        # which draw produced this pixel
gpa scene find --predicate material:transparent
gpa scene get                            # full scene metadata
gpa scene camera                         # camera params
```

## Source and upstream workflow

```bash
gpa source read main.c                   # buggy app source
gpa source grep "glDepthFunc"            # search the buggy app
gpa upstream read src/Engine.cpp         # upstream framework source
gpa upstream grep "render_pass" --glob "*.cpp"
```

## Frame-vs-frame diff

```bash
gpa diff frames --a 1 --b 2 --depth drawcalls
```

## Do NOT do without explicit user approval

- `gpa control pause|resume|step` — alters live capture state
- `gpa annotations add` — writes to the frame
- `gpa frames metadata set` — writes to the frame
- `gpa drawcalls sources set` — registers source mappings on the engine

## Examples

```bash
gpa frames overview
gpa drawcalls textures --dc 42
gpa pixel explain --x 640 --y 360
```
