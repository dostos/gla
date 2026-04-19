# Eval Scenario Format — Honest Eval

## Problem with Current Format

Our scenario.md files describe the ROOT CAUSE in the bug description:
> "A model matrix with negative scale on one axis has a negative determinant,
> which flips triangle winding in clip space from CCW to CW"

This is cheating. A real developer would see:
> "On WebGPU only, setting negative Y scale makes the mesh look inside-out"

## Required Format for Fair Eval

Each scenario.md should have TWO description sections:

### `## User Report` (what the agent sees)
The original issue text — symptoms only, no root cause analysis.
Copy from the GitHub issue or Stack Overflow question verbatim.

### `## Ground Truth` (what we score against)  
Our root cause analysis — hidden from the agent during eval.
Used only by the scorer to check if the diagnosis is correct.

## Example

```markdown
# R20: Mesh invisible with negative scale

## User Report
"On WebGPU only (not the WebGL2 fallback), setting a negative Y scale
on a mesh inverts the front-face direction. The mesh appears inside-out
or disappears entirely. Works fine on WebGL2."

## Ground Truth
The WebGPU backend's _getPrimitiveState() unconditionally sets
frontFace=CCW without checking matrix determinant. When det < 0,
triangle winding flips but frontFace isn't compensated.
Fix: check object.matrixWorld.determinant() and flip frontFace.
```

## For the Eval Harness

- `run_eval(mode="code_only")`: agent sees User Report + source code
- `run_eval(mode="with_opengpa")`: agent sees User Report + source code + OpenGPA data
- Scorer compares agent's DIAGNOSIS against Ground Truth keywords
- Agent NEVER sees Ground Truth section
