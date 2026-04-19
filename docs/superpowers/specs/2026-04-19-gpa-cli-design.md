# `gpa` CLI — Design Spec

**Date:** 2026-04-19
**Status:** design; not yet implemented
**Motivation:** Round 5 eval showed the REST API is token-inefficient (verbose JSON, agents carrying 241K extra cache_read tokens per run, plus the "additive use" problem where agents query GPA *and* still read source files). A CLI surface with plain-text output and a single diagnostic-report default is expected to cut both per-call envelope tax and per-turn context inflation.

## Goals

- **Token-efficient** — plain text; one call diagnoses most bugs.
- **Launch-time capture only** — no retroactive attach for native GL (not feasible).
- **Shell-composable** — exit codes, stdin/stdout, `grep`-friendly output.
- **Same engine** — CLI wraps the existing FastAPI engine; no new runtime.
- **Parity with MCP** — every CLI command maps 1:1 to an MCP tool; ship CLI first, wrap second.

## Non-goals

- Retroactive attach to running binaries (native GL cannot do it without brittle gdb injection).
- Replacing REST API — REST stays for programmatic access; CLI is the agent-facing surface.
- Shader-level debugging / stepping — out of scope; separate work item.

## Architecture

```
+----------------+     JSON-over-Unix-socket    +-----------------+
|   gpa CLI      | <---------------------------> |  gpa engine    |
| (talks to a    |                                | (existing      |
|  running       |                                |  FastAPI       |
|  engine)       |                                |  process)      |
+----------------+                                +-----------------+
                                                          ^
                                                          | LD_PRELOAD'd shim
                                                          | writes to engine's shm
                                                          |
                                                  +-------+--------+
                                                  | target binary  |
                                                  | (./my_gl_app)  |
                                                  +----------------+
```

One engine per session. Session = directory containing socket, shm name, auth token, captured frames manifest.

## Session model

- Default session dir: `/tmp/gpa-session-<uid>-<timestamp>/`
- Each session contains:
  - `socket` — Unix domain socket for engine's REST (`SCGI`-style or plain HTTP over UDS)
  - `shm-name` — POSIX shm identifier for frame capture
  - `token` — bearer token (32 hex chars, 0600 perms)
  - `frames/` — on-disk spill for finished frames (JSON manifest + PNG framebuffers)
  - `engine.pid` — daemon pid
  - `engine.log` — daemon stdout/stderr
- Current-session pointer: `/tmp/gpa-session-current` (symlink to the active session dir)
- `gpa run` creates a session, tears it down on command exit.
- `gpa start` creates a session and leaves it running; `gpa stop` removes it.
- `GPA_SESSION` env overrides auto-discovery.

## Command surface

### Session lifecycle

#### `gpa run [--port N] [--session DIR] [--] <command> [args...]`

Launch `<command>` under the GL shim, capture frames while it runs, stop the engine on exit. Convenience for one-shot scripted flows.

**Flags:**
- `--port N` — REST port (default: ephemeral, bound to session socket)
- `--session DIR` — explicit session path (default: `/tmp/gpa-session-<uid>-<ts>/`)
- `--timeout SECONDS` — kill the target after N seconds (default: no timeout)
- `--` — separator before the target command (so `--port` etc. aren't consumed)

**Exit:** whatever exit code the target binary returns.

**Stdout:** the target binary's stdout, verbatim.
**Stderr:** engine startup banner (one line: `[gpa] session /tmp/...`) then the target's stderr.

**Example:**
```bash
gpa run -- ./my_gl_app --flag=value
[gpa] session /tmp/gpa-session-1000-1713495600/
...target output...
[gpa] captured 42 frames. Run `gpa report` to diagnose.
```

---

#### `gpa start [--session DIR] [--daemon]`

Start a session without launching a target. Useful for interactive workflows, CI, WebGL.

**Flags:**
- `--session DIR` — explicit session path
- `--daemon` — detach (default: foreground; prints session info then blocks)

**Stdout:** single-line session path + env var export block. Suitable for `eval "$(gpa start --daemon)"`.

**Example:**
```bash
$ gpa start --daemon
/tmp/gpa-session-1000-1713495600/
export GPA_SESSION=/tmp/gpa-session-1000-1713495600/
export LD_PRELOAD=/usr/lib/gpa/libgpa_gl.so
export GPA_SOCKET_PATH=/tmp/gpa-session-.../socket
export GPA_SHM_NAME=gpa-shm-abc123
```

**Exit:** 0 on successful startup, 1 on port/socket conflict.

---

#### `gpa stop [--session DIR]`

Stop the current (or specified) session. Terminates daemon, unlinks socket/shm, removes session dir.

**Exit:** 0 on clean stop, 2 if no session found.

---

#### `gpa env [--session DIR]`

Print shell-eval'able env exports for the current session. Separate command from `start` so users can re-print env without restarting.

**Stdout:**
```
export GPA_SESSION=/tmp/gpa-session-.../
export LD_PRELOAD=/usr/lib/gpa/libgpa_gl.so
export GPA_SOCKET_PATH=/tmp/gpa-session-.../socket
export GPA_SHM_NAME=gpa-shm-abc123
```

**Exit:** 0 if session found, 2 if not.

---

### Diagnostics (the token-efficient core)

#### `gpa report [--frame FRAME] [--json]`

Run every derived diagnostic check on the specified frame (default: latest) and print a plain-text report. **This is the intended first query in any session.**

**Checks (initial set, extensible):**

| Check | Triggers when |
|---|---|
| `empty-capture` | frame has 0 draw calls |
| `feedback-loops` | any draw call samples a texture that's also a current FBO attachment |
| `nan-uniforms` | any uniform has NaN/Inf components |
| `mrt-mismatch` | draw call has shader `out_locations > bound_attachments` (stretch) |
| `index-overflow` | `index_count * sizeof(index_type) > max_index_buffer_size` or unsigned_short with >65K vertices expected |
| `missing-clear` | depth test enabled across frames but no `glClear(GL_DEPTH_BUFFER_BIT)` between |
| `state-leak` | pipeline state on draw N differs from draw N-1 without explicit `glEnable`/`glDisable` between |

**Output (default plain text):**

```
gpa report — frame 2 (session /tmp/gpa-session-.../)
42 draw calls captured

⚠ feedback-loop: draw call 3
  texture 7 bound as sampler (slot 0) AND COLOR_ATTACHMENT0
  fix: unbind sampler or render to different FBO

⚠ nan-uniforms: draw call 5
  uRoughness (vec3): component 0 = NaN
  uSpecularity (vec4): components 1,2 = NaN

✓ mrt-mismatch: none
✓ index-overflow: none
✓ missing-clear: none
✓ state-leak: none

3 warnings. Run `gpa check <name>` for details.
```

**Flags:**
- `--frame N` — specific frame (default: `latest`)
- `--json` — JSON output instead of text (for scripts / MCP wrapping)
- `--only <check1,check2>` — run only specific checks
- `--skip <check>` — skip specific checks

**Exit:**
- `0` — no warnings
- `3` — one or more warnings (agents / CI can detect via `$?`)
- `1` — report failed (engine down, bad frame id, etc.)
- `2` — no session

**Token target:** ≤ 300 tokens for a clean report, ≤ 600 for a 5-warning report.

---

#### `gpa check <check-name> [--frame N] [--dc N] [--json]`

Drill-down into one diagnostic. Same checks as `report`, but with full detail.

**Args:**
- `<check-name>` — one of the checks from `report`
- `--frame N` — default `latest`
- `--dc N` — filter to one draw call (checks that return per-dc findings)
- `--json` — structured output

**Example:**
```bash
$ gpa check feedback-loops --frame 2
dc=3  fbo=1  attachment=COLOR_ATTACHMENT0  tex_id=7
      sampler_bindings: slot=0(tex_id=7, shader `tTransmission`)
      location: sampled in fragment shader, unit 0
```

**Exit:** 0 if check passed (no findings), 3 if findings, 1 on error.

---

### Raw data (drill-down, opt-in verbose)

#### `gpa dump <what> [args] [--format=plain|json|compact]`

| `<what>` | args | output |
|---|---|---|
| `drawcalls` | `--frame N` | list: `id primitive n_verts shader_id` |
| `drawcall` | `--frame N --dc N` | full detail (matches REST `/drawcalls/{id}`) |
| `shader` | `--frame N --dc N` | source + decoded uniforms |
| `textures` | `--frame N --dc N` | bound textures table |
| `pixel` | `--frame N --x X --y Y` | `rgba=... depth=... stencil=...` |
| `pipeline` | `--frame N --dc N` | depth/stencil/cull/blend config |
| `frame` | `--frame N` | overview only |

**Format:**
- `plain` (default) — tab-aligned columns, one finding per line
- `json` — structured, matches REST response
- `compact` — single-line key=val pairs (grep-friendly)

---

### Comparison / history

#### `gpa diff <frameA> <frameB> [--what=summary|drawcalls|pixels]`

Compare two captured frames. Thin wrapper over existing `/compare_frames` REST route.

#### `gpa frames`

List all captured frames in the current session.

---

### Annotations (Tier-3 precursor)

#### `gpa annotate --frame N <KEY=VALUE>...`

POST key-value annotations to the current frame. Same data as `POST /frames/{id}/annotations`. For plugin authors who want shell-level annotation.

#### `gpa annotations --frame N`

GET all annotations for a frame.

---

## Global flags

Apply to all subcommands:

- `--session DIR` — explicit session (overrides env)
- `--quiet` / `-q` — suppress non-essential output (gpa banner, etc.)
- `--verbose` / `-v` — debug-level logging on stderr
- `--help` / `-h` — per-command help
- `--version` — print version and exit

---

## Environment variables

| Var | Purpose | Default |
|---|---|---|
| `GPA_SESSION` | Explicit session dir | auto-discover |
| `GPA_SOCKET_PATH` | Unix socket for REST | `$GPA_SESSION/socket` |
| `GPA_SHM_NAME` | POSIX shm id | `$GPA_SESSION/shm-name` |
| `GPA_TOKEN` | Bearer token | `$GPA_SESSION/token` |
| `GPA_PORT` | TCP REST port (optional — UDS is default) | unset |
| `NO_COLOR` | Disable ANSI in report output | unset |

---

## Exit codes (standardized)

| Code | Meaning |
|---|---|
| 0 | Success, no warnings |
| 1 | Error (network, bad args, etc.) |
| 2 | No session / session not found |
| 3 | Diagnostics flagged issue(s) |
| 4 | Capture empty (no draws) |

---

## Output conventions

**Plain-text report lines:**

```
⚠ <check-name>: <summary>
  <detail-line-1>
  <detail-line-2>
  fix: <short actionable>
```

**✓** = check ran, no findings. **⚠** = findings. **✗** = check failed to run.

Always one blank line between warnings. Use ANSI colors iff stdout is a TTY and `NO_COLOR` unset.

Field names in detail lines: `snake_case`, tab-aligned on the first char. Agents can parse.

---

## Implementation plan (summary)

Phase 1 — minimum viable CLI (rough: 1–2 days):
1. `gpa run`, `gpa start`, `gpa stop`, `gpa env` — session lifecycle (wrap existing `gpa.launcher`)
2. `gpa report` (plain-text + `--json`) — implements 4 initial checks: `empty-capture`, `feedback-loops`, `nan-uniforms`, `missing-clear` (the rest can come later)
3. `gpa check <name>`, `gpa dump <what>` — thin REST wrappers

Phase 2 — MCP wrap:
4. One MCP tool `gpa_report(frame_id)` that execs `gpa report --json`
5. One MCP tool `gpa_check(frame_id, check_name)` that execs `gpa check`

Phase 3 — measurement:
6. Re-run Round 5 eval with the CLI available (alongside REST), non-directive prompt
7. Compare: does cache_read drop from +241K to ≤+50K? Does per-pair cost delta go negative?

---

## Open questions

1. **Should `gpa report` be deterministic across checks?** — order of warnings, check ordering for reproducibility. Proposed: fixed order per check name.
2. **Daemon vs embedded engine for `gpa run`?** — simpler is embedded (engine child-process dies with target). Daemon wins for multi-query interactive flows. Propose: `gpa run` = embedded; `gpa start/stop` = daemon.
3. **Authenticate between CLI and engine?** — token in file works; consider SO_PEERCRED on the UDS for even simpler auth within same UID.
4. **Multi-session?** — MVP is single-session (one active at a time per UID). Multi-session via `GPA_SESSION` explicit is fine.

---

## Non-feature: `gpa attach <pid>`

Explicitly deferred. Native GL cannot be retroactively hooked without gdb-level process injection (`ptrace` + `call dlopen("libgpa_gl.so")`), which is fragile, requires debug symbols, and fights ASLR. **Recommendation in error messages: "attach not supported; stop the process and `gpa run -- <cmd>` instead."**
