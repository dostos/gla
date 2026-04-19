# E15_UNIFORM_VALUE_LEAKED_GLUSEPROGRAM_SWITCH_OLD_UTINT_STILL_APP: Stale uTint across glUseProgram switch

## Bug
The app sets `uTint = (1,0,0,1)` on program A, then calls `glUseProgram(progB)` and draws without re-setting `uTint`, assuming the uniform "carries over" because both programs declare `uniform vec4 uTint`. Uniform state is per-program, so program B's `uTint` is still at its default `(0,0,0,0)`.

## Expected Correct Output
The center pixel is covered by program B's quad and — if the author's mental model were correct — would show the red tint left over from program A: RGBA ≈ (255, 0, 0, 255).

## Actual Broken Output
The center pixel is RGBA (0, 0, 0, 0). Program B writes `vec4(0,0,0,0)` because its own `uTint` slot was never written and defaults to zero, wiping out the cleared gray beneath it.

## Ground Truth Diagnosis
In OpenGL, uniform values are part of program-object state, not context state. Declaring a uniform with the same name in two programs does not share storage — each program has its own uniform table, initialized to zero at link time. After `glUseProgram(progB)`, program A's `uTint` assignment is irrelevant; program B samples its own (still-zero) `uTint`, so the fragment shader outputs `(0,0,0,0)`.

## Difficulty Rating
**Moderate (3/5)**

The two shader sources are byte-identical and the uniform name matches exactly, so the source strongly implies a shared slot. The bug is invisible in the C code — you have to remember that uniforms are per-program.

## Adversarial Principles
- **Stale state**: a value set on one program looks "alive" but is silently discarded at the `glUseProgram` boundary.
- **Implicit coupling**: identical uniform names across two programs suggest a shared binding that does not exist in GL's data model.

## How OpenGPA Helps

The specific query that reveals the bug:

```
inspect_drawcall(frame=2, index=1)
```

`inspect_drawcall` returns the active program and the resolved values of its uniforms at draw-call time. For draw 1 it reports `program=progB` with `uTint=(0,0,0,0)` — not the `(1,0,0,1)` last written on progA's `uTint` in draw 0. Seeing the zero directly attributed to program B's uniform table makes the per-program scoping rule — and the missing second `glUniform4f` — immediately obvious.

## Tier
core

## API
opengl

## Framework
none

## Bug Signature
```yaml
type: unexpected_state_in_draw
spec:
  rule: "uTint on draw call 1 (program B) should be (1.0, 0.0, 0.0, 1.0) as last set on program A; actual is (0.0, 0.0, 0.0, 0.0) because uniform state is per-program"
  draw_call_index: 1
  uniform_name: "uTint"
  expected_value: [1.0, 0.0, 0.0, 1.0]
  actual_value: [0.0, 0.0, 0.0, 0.0]
```