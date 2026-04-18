# OpenGPA Eval — Next Steps

## What We Learned

Minimal single-file reproductions (200 lines) are too easy for any LLM model tier.
All 3 rounds: 100% accuracy for both code-only and with-OpenGPA across Haiku and Sonnet.

**Root cause**: The bug IS the entire codebase. There's nothing to search through.

## What Would Show OpenGPA's Value

OpenGPA's value appears when the agent must choose between:
- **Reading 50,000 lines** of framework source to trace state (expensive, slow)
- **Querying 3 OpenGPA endpoints** to see the actual runtime state (cheap, fast)

This requires eval scenarios that include the **actual upstream codebase**, not a minimal reproduction.

## The Plan: Real Codebase Eval

### Setup
1. Use `SnapshotFetcher` to clone upstream repos at the pre-fix commit SHA
2. Give the agent: upstream source (Three.js/Godot) + the bug report + the app code
3. The agent must find the root cause in the framework source

### Two Modes
- **Code-only**: Agent reads bug report + app code + framework source. Must grep/read through framework files to find the state management bug. Token-expensive.
- **With OpenGPA**: Agent reads bug report + app code + queries OpenGPA for runtime state. Can skip reading framework source entirely if the captured state reveals the issue.

### Metrics
- **Tokens consumed**: How much framework source did the agent read?
- **Files opened**: How many framework files did the agent explore?
- **Accuracy**: Did it find the correct root cause?
- **Time**: Wall clock to diagnosis

### Expected Results
- Code-only: reads 5-20 framework files (10,000-50,000 tokens) to trace the state
- With OpenGPA: reads 0-2 framework files (0-5,000 tokens) because the runtime state directly shows the problem

### Candidates (from SnapshotFetcher)

Scenarios that already have upstream snapshot references:
- Issues with `upstream_snapshot.repo` and `upstream_snapshot.sha` in their metadata
- The snapshot contains the actual buggy framework code at the pre-fix commit
- The `relevant_files` list tells which framework files contain the root cause

### Implementation
1. `SnapshotFetcher.fetch(repo, sha)` → clones to `/data3/snapshots/{repo}/{sha}/`
2. Eval agent gets the snapshot path as a "working directory" to explore
3. For code-only: agent can `Read` any file in the snapshot
4. For with-OpenGPA: agent can also query the REST API

### Priority Candidates (multi-file, state bugs)

| Issue | Framework | Root Cause Location | Files to Read |
|-------|-----------|--------------------|----|
| three.js #26762 (depthMask) | Three.js r157 | `src/renderers/webgl/WebGLState.js` | ~5 files |
| three.js #25618 (texture cache) | Three.js r155 | `src/renderers/webgl/WebGLTextures.js` | ~8 files |
| godot #76334 (blend equation) | Godot 4.1 | `drivers/gles3/rasterizer_scene_gles3.cpp` | ~10 files |
| three.js #32444 (transmission) | Three.js r182 | `src/renderers/webgl/WebGLRenderer.js` | ~6 files |

## Status

- [x] Minimal reproduction eval (rounds 1-3): 100% accuracy, too easy
- [x] Curation pipeline discovers real issues
- [x] SnapshotFetcher clones upstream repos
- [x] Scenarios have upstream_snapshot metadata
- [ ] Eval harness passes snapshot path to agents
- [ ] Run multi-file eval with upstream source
- [ ] Measure token reduction from OpenGPA
