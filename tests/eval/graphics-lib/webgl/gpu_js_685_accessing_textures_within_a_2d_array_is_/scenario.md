# R206: gpu.js — accessing textures inside a 2D array of textures is impossible

## User Report
I'm passing a 2D array of textures (an array whose entries are arrays of images) into a `gpu.js` kernel and trying to read RGBA values out of them. I expected to be able to write something like

```
parameter[2][13][y][x][0];   // R channel
return parameter[2][13][y][x];
```

inside the kernel body, where `y,x` correspond to the kernel size. Even just

```
const o = parameter[2];
const b = o[13];
```

fails. The kernel compile throws:

```
Uncaught Error: Error compiling fragment shader:
ERROR: 0:619: 'user_oSize' : undeclared identifier
ERROR: 0:619: 'user_oDim' : undeclared identifier
ERROR: 0:619: 'getMemoryOptimized32' : no matching overloaded function found
...
```

A much simpler reproduction also blows up:

```js
const GPU = await import('https://cdn.jsdelivr.net/npm/gpu.js@2.16.0/+esm')
const ctx = new GPU.default.GPU()
ctx.createKernel(function (a) { return a[1-1]; }).setOutput([1])([1])
```

This is `gpu.js` 2.16.0 on a recent Chrome/WebGL2 stack. Indexing more than 4 levels deep into the parameter (`parameter[2][13][1][1][0]`) gives a different error — `Unexpected expression on line 153, position 17`. Single-level indexing with a literal works, but nothing beyond that.

## Expected Correct Output
Indexing into a parameter that is an array of textures (or an array of arrays of textures) inside a kernel should compile and return the RGBA pixel values from the chosen texture, the same way passing a single texture parameter does.

## Actual Broken Output
The kernel fails to compile at all. The shader error log references `user_oSize`, `user_oDim`, and a `getMemoryOptimized32` overload that does not exist, which all point at the GLSL the framework's codegen emitted for the array index expression. Deeper-than-4-level indexing fails earlier, in the JS-side AST walker, with `Unexpected expression`.

## Ground Truth
The bug is in `gpu.js`'s kernel-to-GLSL code generator, not in user code. A community reproduction in the issue thread isolates the failure to a single root cause: when the kernel body contains an integer-typed index expression that the codegen has typed as `float`, the generated GLSL passes that float into a function whose signature requires `int`, and emits identifier names (`user_<name>Size`, `user_<name>Dim`) that the surrounding shader never declared for the inner array level.

A maintainer/contributor distilled this in the thread:

> Minimum reproducible code example:
> ```js
> ctx.createKernel(function (a) {return a[1-1];}).setOutput([1])([1])
> ```
>
> # Caused by
> In compiled code...
> ```glsl
> float getMemoryOptimized32(sampler2D tex, ivec2 texSize, ivec3 texDim, int z, int y, int x) { /* ... */ }
>
> getMemoryOptimized32(user_GPUu_uargument_0, user_GPUu_uargument_0Size, user_GPUu_uargument_0Dim, 0, 0, /* unmatched float, expected int */ (1.0-1.0));
> ```

See https://github.com/gpujs/gpu.js/issues/685 — the same comment also documents the JS-level workaround:

> By replacing `(1.0-1.0)` with `int(integerCorrectionModulo(float((1.0-1.0)), /* Infinity */ intBitsToFloat(2139095039)))` we can get a integer with some little overheads and keep compatibility with Javascript.

The two failure modes the user sees collapse into the same defect: (1) for shallow indices the codegen substitutes a float-literal expression where the `getMemoryOptimized*` overload demands `int`, and emits the inner array's `*Size` / `*Dim` symbol names without declaring them; (2) for indices deeper than 4 levels, the AST walker that lowers `MemberExpression` chains gives up before reaching codegen and throws `Unexpected expression`. A correct fix lives inside the gpu.js codegen, in the function/file responsible for emitting integer index expressions and for resolving nested-array parameter symbols (typical area: `src/backend/web-gl/function-node.js` / `src/backend/web-gl2/function-node.js` and the array-parameter handling in `src/utils.js` / `src/backend/function-node.js`).

No merged fix PR is identifiable from the issue thread or its linked context as of the issue's last activity — the thread surfaces a workaround but no resolution PR — so this draft is retained as a `legacy` bug-pattern reference.

## Fix
```yaml
fix_pr_url: (none — issue unresolved at thread close; no fix PR identifiable from https://github.com/gpujs/gpu.js/issues/685)
fix_sha: (auto-resolve from issue #685)
fix_parent_sha: (auto-resolve from issue #685)
bug_class: legacy
framework: gpu.js
framework_version: 2.16.0
files: []
change_summary: >
  Fix PR not resolvable from the issue thread alone. The defect lives in
  the gpu.js kernel-to-GLSL code generator: integer-typed index expressions
  are emitted as floats into functions whose signatures require int, and
  nested-array parameter symbols (*Size, *Dim) are referenced without being
  declared. Scenario retained as a legacy bug-pattern reference for shader
  codegen type-mismatch and undeclared-identifier failures.
```

## Flywheel Cell
primary: framework-maintenance.web-3d.code-navigation
secondary:
  - framework-maintenance.web-3d.captured-literal-breadcrumb
  - framework-maintenance.web-3d.shader-codegen-type-mismatch

## Difficulty Rating
4/5

## Adversarial Principles
- bug-lives-inside-framework-codegen-not-user-kernel
- shader-error-log-points-at-generated-glsl-not-source
- diagnosis-requires-reading-emitted-glsl-not-pixel-comparison
- legacy-bug-no-merged-fix-pr-to-anchor-on

## How OpenGPA Helps
Capturing the failed `glCompileShader` with OpenGPA's GL shim surfaces the framework-generated GLSL source and the InfoLog verbatim — including the offending `getMemoryOptimized32(..., (1.0-1.0))` call site and the undeclared `user_oSize` / `user_oDim` identifiers. Querying `/api/v1/frames/current/shaders/<id>/source` plus `/api/v1/frames/current/shaders/<id>/log` lets the agent jump from a JS-level "kernel compile failed" symptom directly to the line of emitted GLSL, which then points at the codegen branch in gpu.js that produced it. Without OpenGPA the agent only sees the JS exception text and must reverse-engineer the codegen path from the kernel source.

## Source
- **URL**: https://github.com/gpujs/gpu.js/issues/685
- **Type**: issue
- **Date**: 2021-04-21
- **Commit SHA**: (none — no fix PR identified)
- **Attribution**: Reported by @andrewbrg; diagnosis with reduced repro and emitted-GLSL analysis contributed by a thread participant on https://github.com/gpujs/gpu.js/issues/685.

## Tier
maintainer-framing

## API
opengl

## Framework
gpu.js

## Bug Signature
```yaml
type: code_location
spec:
  expected_files: []
  fix_commit: (none)
  notes: >
    Legacy scenario — no merged fix PR. Scoring should credit the agent
    for localizing to the gpu.js codegen layer (typical area:
    src/backend/web-gl/function-node.js, src/backend/web-gl2/function-node.js,
    or the nested-array parameter handling in src/backend/function-node.js
    / src/utils.js) rather than to a user kernel file.
```

## Predicted OpenGPA Helpfulness
- **Verdict**: yes
- **Reasoning**: The user-visible error is a JS exception, but the actual defect is in the GLSL the framework synthesized. OpenGPA's shim captures `glShaderSource` and `glGetShaderInfoLog` so the agent can read the emitted GLSL and the compile log directly, which is exactly the evidence the maintainer used in the upstream thread to pinpoint the float-vs-int mismatch and the undeclared `*Size`/`*Dim` identifiers.