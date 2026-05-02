# R13: Bevy clustering bind group rejected on WebGPU — read-write SSBO visible to Vertex stage

## User Report

Bevy `main` since #23036 (the GPU-clustering-for-lights change). The
`pbr` example, built with the WebGPU backend, flickers and freezes
black; the same issue blocks rendering on Android (#23208) and in
the iOS simulator (#23428).

Repro:

```
cargo run --package build-wasm-example -- --api webgpu pbr
```

Browser console emits:

```
ERROR Caught rendering error:
  Read-write storage buffer binding is used with a visibility
  (ShaderStage::(Vertex|Fragment)) that contains ShaderStage::Vertex
  (note that read-only storage buffer bindings are allowed).
   - While validating entries[1]
   - While validating [BindGroupLayoutDescriptor "clustering count pass bind group layout"]
   - While calling [Device].CreateBindGroupLayout(...)

ERROR Caught rendering error:
  [Invalid BindGroupLayout "clustering count pass bind group layout"] is invalid.
   - While validating [BindGroupDescriptor "clustering count pass bind group"]
     against [Invalid BindGroupLayout "clustering count pass bind group layout"]
   - While calling [Device].CreateBindGroup(...)
```

## Expected Correct Output

The `pbr` example renders correctly on WebGPU and on the WebGPU-spec
mobile profile (Android + iOS).

## Actual Broken Output

The clustering-count-pass bind group layout declares its read-write
storage buffer binding with `visibility = Vertex | Fragment`. The
WebGPU spec forbids vertex shaders from holding read-write storage
buffers; `wgpu` accepts this on some desktop hardware as an extension
but the underlying browser implementations and many mobile GPUs
correctly reject it. The bind group layout fails to validate, the
bind group never instantiates, and the entire rasterized clustering
path is unable to bind, producing a black/flickering result.

The pre-fix code: every read-write SSBO in the clustering rasterizer
path is exposed at `ShaderStages::VERTEX_FRAGMENT`. None of the
vertex shaders actually read or write those buffers — only the
fragment shaders do — but the visibility flag was set conservatively.

## Ground Truth

Per the fix PR ("Don't let the clustering vertex shader see any
read-write storage buffers."):

> The WebGPU spec forbids vertex shaders from having read-write
> storage buffers attached. As an extension, `wgpu` allows this on
> some hardware, but many mobile GPUs don't support it either.
> Because our bind group for GPU clustering rasterization specified
> `VERTEX_FRAGMENT` for all bindings, this was causing errors, even
> though we never actually used those read-write storage buffers in
> any vertex shaders.
>
> This commit should fix the issue, by putting all read-write SSBO
> bindings behind `#ifdef`s and changing the `ShaderStages` for those
> bindings to `FRAGMENT`.

The fix changes `ShaderStages::VERTEX_FRAGMENT → FRAGMENT` for all
read-write SSBO bindings in `crates/bevy_pbr/src/cluster/gpu.rs` and
guards the matching declarations in
`crates/bevy_pbr/src/cluster/cluster_raster.wgsl` with `#ifdef`s.

See https://github.com/bevyengine/bevy/pull/23256 (fixes #23216,
related #23208 #23428).

## Fix
```yaml
fix_pr_url: https://github.com/bevyengine/bevy/pull/23256
fix_sha: 7fc2e2da3078d6ce387ecff842437b122daa4532
fix_parent_sha: d7c5621f3afd3cf58154a3f3f614c909e4529783
bug_class: framework-internal
framework: bevy
framework_version: main@post-23036
files:
  - crates/bevy_pbr/src/cluster/cluster_raster.wgsl
  - crates/bevy_pbr/src/cluster/gpu.rs
change_summary: >
  The clustering rasterizer's bind group layout declared read-write
  storage buffers visible to both vertex and fragment shaders.
  Per WebGPU spec, vertex shaders may not see read-write storage
  buffers; the layout was therefore invalid on WebGPU, Android, and
  iOS-simulator targets, even though the vertex shaders never
  actually used those buffers. The fix narrows the visibility flag
  to `ShaderStages::FRAGMENT` and guards the SSBO declarations in
  `cluster_raster.wgsl` with `#ifdef`s so the vertex stage doesn't
  see them.
```

## Upstream Snapshot
- **Repo**: https://github.com/bevyengine/bevy
- **SHA**: d7c5621f3afd3cf58154a3f3f614c909e4529783
- **Relevant Files**:
  - crates/bevy_pbr/src/cluster/cluster_raster.wgsl
  - crates/bevy_pbr/src/cluster/gpu.rs

## Flywheel Cell
primary: framework-maintenance.game-engine.code-navigation
secondary:
  - framework-maintenance.game-engine.captured-bind-group-validation-breadcrumb

## Difficulty Rating
3/5

## Adversarial Principles
- bug-lives-inside-framework-not-user-code
- backend-spec-conformance-gap-desktop-vulkan-permissive-mobile-webgpu-strict
- visibility-flag-overscoped-shader-doesnt-actually-use-the-binding

## How OpenGPA Helps

The captured frame on a Vulkan-desktop run will succeed (the
permissive `wgpu` desktop path), while the WebGPU run produces no
captured frames at all (the bind group layout never validates so no
draw calls reach the device). `gpa frame-diff vulkan-frame
webgpu-frame` makes the absence of the clustering pass on WebGPU
explicit. The agent can then cross-reference the wgpu validation log
("Read-write storage buffer binding ... ShaderStage::Vertex") with
the small set of `BindGroupLayout` builders that include
`VERTEX_FRAGMENT` — pointing at `cluster/gpu.rs` directly.

## Source
- **URL**: https://github.com/bevyengine/bevy/issues/23216
- **Type**: issue
- **Date**: 2026-03-04
- **Commit SHA**: 7fc2e2da3078d6ce387ecff842437b122daa4532
- **Attribution**: Reported by @mockersf in bevy#23216 (also #23208, #23428); fix in PR #23256.

## Tier
maintainer-framing

## API
vulkan

## Framework
bevy

## Bug Signature
```yaml
type: code_location
spec:
  expected_files:
    - crates/bevy_pbr/src/cluster/gpu.rs
  fix_commit: 7fc2e2da3078d6ce387ecff842437b122daa4532
```

## Predicted OpenGPA Helpfulness
- **Verdict**: yes
- **Reasoning**: The captured-frame contrast (Vulkan: clustering
  pass present; WebGPU: clustering pass absent) is the strongest
  possible signal that the bug is a backend-spec conformance gap,
  not a shader bug. The agent is then forced to investigate the
  bind group **layout** (the only thing that differs between the
  two backends in how that pass binds) — pointing at `cluster/gpu.rs`.
  Without the capture, the symptom ("WebGPU is black") is too
  unspecific and the agent might chase shader compilation issues
  or texture format issues that aren't the cause.

## Observed OpenGPA Helpfulness
- **Verdict**: no
- **Evidence**: code_only baseline scored 1.0 on file-level identification (Claude Code Explore subagent against the bevy snapshot at fix_parent_sha, ~20 file reads, ~30s wall time). The user-report keywords map directly onto the bug-bearing file path, leaving no headroom for runtime capture to add value. See docs/superpowers/eval/round13/bevy-code-only-results.md.
