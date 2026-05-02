# OpenGPA CLI + Multi-Backend Eval Design

**Date:** 2026-05-02
**Status:** Draft (brainstorming output, pending user approval)
**Author:** Jingyu (with codex `cli-creator` skill input)

## Goal

Make the OpenGPA evaluation pipeline backend-agnostic. Today it is hard-wired to the Anthropic SDK with native tool-use, and the agent reaches the engine through an MCP server whose per-turn tool schemas dominate context tokens. After this change:

1. The eval harness can drive the agent loop with one of three interchangeable backends — `api` (Anthropic SDK), `claude-cli`, or `codex-cli`. Adding a fourth (any future MCP-aware or shell-aware CLI) is one preset, not a rewrite.
2. CLI agent backends call into OpenGPA through a unified, low-token shell CLI named `gpa` rather than via MCP. The MCP server is marked deprecated.
3. The curation/text-completion path (`gen_queries`) gets the same backend choice for consistency.

## Non-goals

- Changing the REST API surface.
- Designing new graphics-debugging tools (this is plumbing only).
- Replacing the Anthropic SDK path for users who want native tool-use; that remains the high-fidelity reference backend.
- A long deprecation runway for MCP. We mark deprecated and remove from default paths now; physical deletion is a follow-up.

## Background — what already exists

- `gpa` CLI at `src/python/gpa/cli/`, wired in `pyproject.toml` as `[project.scripts] gpa = "gpa.cli.main:main"`. Existing commands: `start`, `stop`, `env`, `run`, `run-browser`, `report`, `check`, `dump {frame|drawcalls|pixel}`, `frames`, `check-config`, `explain-draw`, `diff-draws`, `scene-find`, `scene-explain`, `trace {uniform|value}`. Naming is mixed: top-level verbs, hyphenated multiword commands, and one `noun verb` (`trace`).
- Eval agent at `src/python/gpa/eval/llm_agent.py`: a single `EvalAgent` class that uses the Anthropic SDK with native tool-use over `GPA_TOOLS` (5 OpenGPA tools + `read_source_file`) and optional `SNAPSHOT_TOOLS` (3 upstream-snapshot tools). `build_agent_fn(...)` is the factory the harness uses.
- Curation LLM client at `src/python/gpa/eval/curation/llm_client.py`: `LLMClient` (Anthropic SDK) and `ClaudeCodeLLMClient` (shell out to `claude -p`). `gen_queries.py` selects between them via `--llm-backend {api,claude-cli}`.
- MCP server at `src/python/gpa/mcp/server.py`: ~17 tools, JSON-RPC over stdio. Substantially broader than what the eval agent calls today.

## Design

### Part 1 — `gpa` CLI redesign (consistent naming)

Adopt the codex `cli-creator` shape: every data command is `gpa <noun> [<sub-noun>] <verb> [args]`. Verbs are short and reused across nouns: `list, get, set, find, explain, diff, read, grep, status, pause, resume, step, add, overview, run`.

**Top-level taxonomy:**

| Layer | Top-level commands | Why kept at top level |
|---|---|---|
| Lifecycle (engine) | `start`, `stop`, `env`, `run`, `run-browser` | Manage the engine process; not API tools |
| Diagnostics (composite) | `report`, `check`, `check-config`, `doctor` | Composite verbs that fan out across the noun set |
| Data nouns | `frames`, `drawcalls`, `pixel`, `scene`, `diff`, `trace`, `passes`, `annotations`, `control`, `source`, `upstream` | The agent's main surface |
| Escape hatch | `request` *(deferred — not in this iteration)* | YAGNI for now |

**Frame addressing:** keep the existing `--frame N` int flag (default = latest). Don't switch to positional `<frame>`. Also accept `--frame latest` as a no-op for clarity. When `GPA_FRAME_ID` is set in the environment and `--frame` is omitted, the CLI uses `GPA_FRAME_ID` as the default *before* falling back to "latest". The eval harness uses this so a scenario's agent always pins to its captured frame without one resolution call per command. Explicit `--frame N` always wins over the env var.

**Renames (old → new, with one-release deprecation aliases):**

| Old | New |
|---|---|
| `gpa frames` | `gpa frames list` |
| `gpa dump frame [--frame N]` | `gpa frames overview [--frame N]` |
| `gpa dump drawcalls [--frame N]` | `gpa drawcalls list [--frame N]` |
| `gpa dump pixel --x --y [--frame N]` | `gpa pixel get --x --y [--frame N]` |
| `gpa explain-draw --frame --draw N` | `gpa drawcalls explain --frame --dc N` |
| `gpa diff-draws --frame --a --b [--scope]` | `gpa drawcalls diff --frame --a --b [--scope]` |
| `gpa scene-find --predicate ...` | `gpa scene find --predicate ...` |
| `gpa scene-explain --x --y ...` | `gpa scene explain --x --y ...` |

`gpa report`, `gpa check NAME`, `gpa check-config`, `gpa trace uniform|value`, and the lifecycle commands keep their current names. The `dump` namespace dies (subsumed by per-noun verbs).

**New commands (MCP parity):**

```
gpa drawcalls shader --frame N --dc N
gpa drawcalls textures --frame N --dc N
gpa drawcalls vertices --frame N --dc N
gpa drawcalls attachments --frame N --dc N
gpa drawcalls nan-uniforms --frame N --dc N
gpa drawcalls feedback-loops --frame N --dc N
gpa drawcalls sources get --frame N --dc N
gpa drawcalls sources set --frame N --dc N (--file PATH | --body-json TEXT)
gpa scene get --frame N
gpa scene camera --frame N
gpa scene objects --frame N [--limit N] [--offset N]
gpa diff frames --a N --b N [--depth summary|drawcalls|pixels]
gpa pixel explain --x N --y N [--frame N]
gpa passes list --frame N
gpa passes get NAME --frame N
gpa annotations list --frame N
gpa annotations add --frame N (--file PATH | --body-json TEXT)
gpa frames metadata get --frame N
gpa frames metadata set --frame N (--file PATH | --body-json TEXT)
gpa control status
gpa control pause
gpa control resume
gpa control step
```

**New commands (harness-local, not REST):**

```
gpa source read PATH [--max-bytes N]
gpa source grep PATTERN [--subdir P] [--glob G] [--max-matches N]
gpa upstream read PATH [--max-bytes N]
gpa upstream list SUBDIR
gpa upstream grep PATTERN [--subdir P] [--glob G] [--max-matches N]
```

Backed by `GPA_SOURCE_ROOT` and `GPA_UPSTREAM_ROOT` env vars set per-scenario by the eval harness. Both have hard caps (default `--max-bytes 200000`, `--max-matches 50`, hard `--max-matches` cap 500), reject absolute paths and `..` traversal, return JSON: `{"path": ..., "bytes": N, "text": ...}` for reads, `{"matches": [{path, line, text}], "truncated": bool}` for grep, `{"subdir": ..., "entries": [{name, type}]}` for list.

**JSON policy (decided):**

- All data commands take `--json` and currently mostly default to plain text. The new commands default to **JSON output with `--text` to opt out**, since the primary user is an LLM agent and JSON-by-default eliminates one flag per call. This is a binding decision, not tentative.
- Existing `--json` commands keep their current default for backward compatibility but are documented as "set `--json` for agent use."
- REST-backed commands pass through API JSON verbatim (no `{"ok":..., "data":...}` envelope on success).
- Errors: stable envelope only on stderr, with nonzero exit code. No envelope on stdout for successes.
- Redaction: never print `GPA_TOKEN` or `Authorization` headers.

**Deferred:** `gpa doctor`, `gpa request {get,post,head}`. Both are useful but not blocking the eval-backend work. Reopen after we see how the agent backends use the CLI in practice.

### Part 2 — Eval agent backend abstraction

Layout:

```
src/python/gpa/eval/agents/
  __init__.py        — re-exports + AgentResult dataclass
  base.py            — AgentBackend ABC: run(scenario, mode, tools) -> AgentResult
  api_agent.py       — current EvalAgent moved here, unchanged behaviour
  cli_agent.py       — new: subprocess-driven backend (claude-cli / codex-cli)
  factory.py         — build_agent_fn(backend, model, max_turns, api_key)
```

`AgentResult` and `GpaToolExecutor` move to this package. `gpa.eval.llm_agent` becomes a thin compatibility shim that re-exports from `gpa.eval.agents` for one release.

**`api_agent.ApiAgent`:** the existing `EvalAgent`, no behaviour changes. Continues using the Anthropic SDK with native tool-use against `GPA_TOOLS` and `SNAPSHOT_TOOLS`. Remains the reference backend.

**`cli_agent.CliAgent`:** a generic subprocess-driven agent. Spec object:

```python
@dataclass(frozen=True)
class CliBackendSpec:
    name: str                  # "claude-cli" | "codex-cli"
    binary: str                # "claude" | "codex"
    base_args: list[str]       # invocation prefix (without prompt)
    stdout_format: Literal["ndjson", "log", "plain"]
    parse_run: Callable[[str, str], CliRunMetrics]
    timeout_sec: int = 1800
```

`stdout_format = "ndjson"` is the parser-side label for newline-delimited JSON events from *any* CLI. It is not the same as Anthropic's specific `claude --output-format stream-json` schema — that's a producer-side flag. Each preset's `parse_run` knows how to read its own producer's events.

Two presets:

- `CLAUDE_CLI_SPEC`: producer args `claude -p --output-format stream-json --verbose`; parser reads Anthropic stream-json events, counts `tool_use` blocks per assistant message, sums `usage.input_tokens` / `usage.output_tokens`, takes the final `result` event's text as the diagnosis.
- `CODEX_CLI_SPEC`: producer args `codex exec --skip-git-repo-check --json -s read-only -C <cwd>`; parser reads codex's NDJSON event stream, counts `local_shell_call` events whose argv starts with `gpa`, takes token counts and final assistant text from the terminal events. Exact event names verified during implementation against a recorded fixture.

`CliAgent.run(scenario, mode, tools)` flow:

1. Compute env: `GPA_BASE_URL`, `GPA_TOKEN` from process env; `GPA_SOURCE_ROOT` from scenario source dir; `GPA_UPSTREAM_ROOT` from snapshot dir if present; `GPA_FRAME_ID` from the captured frame id (with-gla mode).
2. With-gla mode only: invoke `tools["run_with_capture"]()` to build + run the scenario binary and store the frame id.
3. Render the prompt: scenario description, the source-path hint, list of available `gpa` subcommands (one-line each, generated from `gpa --help`), instruction to end with `DIAGNOSIS:` and `FIX:`. Code-only mode swaps in a prompt that lists only `gpa source` / `gpa upstream`.
4. `subprocess.run([binary, *base_args, prompt-on-stdin])` with the env, capture stdout/stderr.
5. Parse via `spec.parse_run(stdout, stderr)`, mapping to `AgentResult`. Tool-call counting filters to invocations of `gpa ...`, ignoring agent-internal shell ops.
6. Return.

The CLI agent does NOT drive a turn-by-turn loop in Python; it hands the prompt to the CLI and reads back. `num_turns` is reported as the parsed event count, not externally controlled. `max_turns` is plumbed as a per-spec timeout instead.

**`factory.build_agent_fn(backend, model, max_turns, api_key=None)`:**

```python
def build_agent_fn(backend: str, *, model: str, max_turns: int = 20,
                   api_key: str | None = None) -> AgentFn:
    if backend == "api":
        return _api_agent_fn(model=model, max_turns=max_turns, api_key=api_key)
    if backend == "claude-cli":
        return _cli_agent_fn(spec=CLAUDE_CLI_SPEC, model=model, timeout_sec=...)
    if backend == "codex-cli":
        return _cli_agent_fn(spec=CODEX_CLI_SPEC, model=model, timeout_sec=...)
    raise ValueError(f"unknown agent backend: {backend!r}")
```

### Part 3 — Curation LLM client (text completion)

Refactor `gpa.eval.curation.llm_client`:

```
LLMResponse                — unchanged
LLMClient                  — unchanged (Anthropic SDK)
_CliLLMClient              — new shared base: subprocess + stdin + stdout-strip
ClaudeCodeLLMClient(_CliLLMClient)
CodexCliLLMClient(_CliLLMClient)
```

`_CliLLMClient.__init__(binary, extra_args, timeout)` and `complete()` collapse the existing `ClaudeCodeLLMClient.complete()` body to one shared implementation. Each subclass sets defaults (`binary="claude"` vs `binary="codex"`) and provides any backend-specific argv.

`gen_queries.py`:

- `--llm-backend` choices: `["api", "claude-cli", "codex-cli"]`.
- `_build_llm_client` adds the `codex-cli` branch.

### Part 4 — Wiring backend selection through entry points

- `gpa.eval.cli` (the user-facing eval CLI in `src/python/gpa/eval/cli.py`): replace the stub agent default with `factory.build_agent_fn(...)` when the user did not pass a real one. Add flags `--agent-backend {api,claude-cli,codex-cli}` (default: `api`) and `--agent-model MODEL`.
- `gpa.eval.curation.run`: the existing `--backend` flag is currently inert (passed to `RunEval` but unused). Wire it through `factory.build_agent_fn` so `--backend codex-cli` actually drives the agent. Default remains `auto` (resolves to `api` when an `ANTHROPIC_API_KEY` is present, else `claude-cli`).

### Part 5 — MCP deprecation

Compressed from codex's 5-phase plan since the user asked for "mark deprecated":

1. **This change**:
   - Add a deprecation header to `src/python/gpa/mcp/server.py` module docstring pointing to `gpa --help`.
   - Add a deprecation banner to `src/python/gpa/mcp/README.md`.
   - Audit imports and remove MCP from any default code path. (Best as I can tell, it's already opt-in.)
   - Update any docs that frame MCP as the preferred agent integration to reference the CLI instead.
2. **Follow-up (not in this PR)**: schedule a cleanup agent in 4 weeks to delete `src/python/gpa/mcp/` and its tests, after confirming no external consumer.

The MCP server is not removed in this change. Anyone who wants to keep using it can; we just stop documenting it as the recommended path.

### Part 6 — Companion skill content

Single source of truth at `docs/cli/agent-integration.md`. Two thin wrappers symlink or include this content:

- `.codex/skills/gpa/SKILL.md` (project-local for codex agents)
- `.claude/skills/gpa/SKILL.md` (project-local for Claude agents)

Skill content (from codex's design, lightly trimmed):

- When to use (debugging an OpenGPA-captured frame)
- Auth and env (`GPA_BASE_URL`, `GPA_TOKEN`, `GPA_SOURCE_ROOT`, `GPA_UPSTREAM_ROOT`, `GPA_FRAME_ID`)
- Frame workflow (`gpa frames overview --frame $GPA_FRAME_ID --json` first)
- Drawcall workflow (`gpa drawcalls list`, then `drawcalls explain` / `drawcalls diff`)
- Pixel and scene workflow
- Source and upstream workflow
- "Do not do without approval" (control pause/resume/step, annotations add, metadata set, sources set)
- Three example invocations

## File touch list

| Area | Files |
|---|---|
| CLI new commands | `src/python/gpa/cli/commands/{drawcalls,pixel,scene_get,scene_camera,scene_objects,diff_frames,passes,annotations,control,source,upstream,frames_metadata}.py` |
| CLI rewiring | `src/python/gpa/cli/main.py` (rename existing parsers, register new ones, add deprecated aliases) |
| CLI infra | `src/python/gpa/cli/rest_client.py` (no change expected); `src/python/gpa/cli/local_roots.py` (new — env-rooted path resolution shared by `source`/`upstream`) |
| Eval agents | `src/python/gpa/eval/agents/{__init__,base,api_agent,cli_agent,factory}.py` (new package); `src/python/gpa/eval/llm_agent.py` becomes a re-export shim |
| Eval entry points | `src/python/gpa/eval/cli.py` (add `--agent-backend`); `src/python/gpa/eval/curation/run.py` (wire `--backend`) |
| Curation LLM client | `src/python/gpa/eval/curation/llm_client.py` (extract base, add codex client); `src/python/gpa/eval/curation/gen_queries.py` (add choice) |
| MCP deprecation | `src/python/gpa/mcp/server.py` (header note); `src/python/gpa/mcp/README.md` (banner) |
| Docs | `docs/cli/agent-integration.md` (new); `.codex/skills/gpa/SKILL.md`; `.claude/skills/gpa/SKILL.md` |
| Tests | `tests/unit/python/cli/test_{drawcalls,pixel,scene,diff,passes,annotations,control,frames_metadata}.py` for new REST-backed namespaces; `tests/unit/python/cli/test_local_roots.py` for `gpa source`/`gpa upstream` (path-traversal rejection, max-bytes/max-matches caps, env-var resolution); `tests/unit/python/eval/agents/test_{factory,cli_agent}.py`; `tests/unit/python/eval/curation/test_codex_cli_client.py` |

## Implementation order

1. **CLI extension** — add `gpa source` / `gpa upstream` commands first (they unblock the harness env-var contract). Add new noun-verb commands incrementally; preserve existing commands as aliases that print a stderr deprecation note.
2. **Agent package split** — move `EvalAgent` to `gpa.eval.agents.api_agent`, add ABC + factory + shim. No behaviour change.
3. **CLI agent backend** — implement `CliAgent` with `CLAUDE_CLI_SPEC`. Smoke-test against one scenario end-to-end.
4. **Codex preset** — add `CODEX_CLI_SPEC` once stream-json/log parsing is verified against real codex output.
5. **Curation `CodexCliLLMClient`** — drop in parallel to `ClaudeCodeLLMClient`. Add `--llm-backend codex-cli` to `gen_queries`.
6. **Wire backend flags** — `--agent-backend` in `gpa.eval.cli`, plumb `--backend` in `curation.run`.
7. **MCP deprecation** — docstring + README + import audit.
8. **Companion skill** — write `docs/cli/agent-integration.md` and the two skill stubs.

Each step is its own commit; (1)–(2) are pure refactor and can land independently.

## Open questions

- **Backwards compatibility:** keep aliases for one release, or rip the band-aid? Current draft: aliases with stderr deprecation, removed in next release.
- **Codex `exec` event format:** designed against `--json` based on `codex exec --help` output. Exact event names and final-message extraction need verification on first integration. May require fallback to `--output-last-message FILE` plus stderr log parsing.
- **MCP physical removal:** should the cleanup happen in 4 weeks (default) or wait until we ship CLI v1?
- **`gpa doctor` / `gpa request`:** punt to a follow-up, or include in this iteration?

## Risks

- **CLI agent metrics fidelity:** stream-json/codex log parsing is a dependency on undocumented or under-documented output formats. If parsing breaks in a future CLI release, eval token counts go to zero. Mitigation: a small CLI-version assertion in the spec presets, plus a regression test that pins the parser against a recorded log fixture.
- **Subprocess timeouts:** the CLI agent is one big subprocess call, not an interactive loop. If the scenario hits a model that loops on `gpa source grep` forever, only the timeout saves us. Default 30 minutes per scenario. Document the knob clearly.
- **MCP users we don't know about:** the codebase is small and the MCP server has no obvious external integrations, but the deprecation notice should explicitly invite feedback in case someone is using it.
