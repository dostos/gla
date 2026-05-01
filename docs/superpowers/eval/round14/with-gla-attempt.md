# R14 with_gla attempt — 2026-05-01

Attempted to run a real Bevy example (the R14 #2
`invisible_after_material_swap` repro) under the OpenGPA Vulkan
layer to test whether real captured frame state lifts the
code_only baseline (33%) for the agent eval.

## Result: blocked on layer-completeness, not on agent ergonomics

The bug **does** reproduce in real Bevy 0.16 at the parent SHA
(verified via pixel readback: control without the OnAdd hook shows
cube colors at expected positions, swap variant shows clear color
only). End-to-end pipeline works:

- `cargo run --example r14_invisible_swap` builds + runs under our
  Vulkan layer
- Layer's IPC handshake succeeds (engine + SHM + control socket)
- 30 frames captured per run via vkQueuePresentKHR
- Pixel readback returns the right pixels (verified by
  control-vs-swap difference on cube positions)

But the **draw call surface is incomplete**: out of every frame
that Bevy submits, our layer sees only 1 vkCmdDraw (the tonemap
fullscreen blit). The 5 cube draws — and the shadow / opaque
passes — go through Vulkan entrypoints we don't intercept on
NVIDIA, even though `ash` correctly loaded our wrappers for them.

## Diagnosis

Per-frame instrumentation on the NVIDIA TITAN RTX (driver
595.58.03) Vulkan path:

| Counter | Per-frame |
|---|---|
| BeginCommandBuffer | ~16 |
| CmdBindPipeline | ~5 |
| CmdDraw | 1 (the tonemap triangle, vc=3 inst=1) |
| CmdDrawIndexed | 0 |
| CmdDrawIndexedIndirect | 0 |
| CmdDrawIndexedIndirectCount | 0 |
| CmdDispatch | 3 (1×1×1 each) |
| CmdExecuteCommands | 0 |
| QueueSubmit | 1 (16 cmd buffers each) |
| QueueSubmit2 | 0 |

`ash` *does* call our `vkGetDeviceProcAddr` for every draw
function name (verified by tracing the lookup pName), and our
layer correctly returns wrapper pointers for the entire family
(unsuffixed + KHR/AMD aliases for the indirect-count variants,
core 1.3 + KHR for `vkCmdBeginRendering`, etc.). But none of those
wrappers fire when wgpu actually issues a draw. The cube draws go
through a code path our intercepts can't see — best guess: the
NVIDIA ICD installs an implicit instance layer of its own that
intercepts these calls *above* our layer in the chain.

## Layer fixes made along the way

The investigation found and fixed several layer bugs:

1. **`vkBeginCommandBuffer` was never wrapped.** `gpa_capture_cmd_buf_begin` was defined in `vk_capture.c` but never called — so `gpa_capture_record_draw`'s lookup against `g_cmd_table` always returned NULL, silently dropping every recorded draw. Wrapped now.

2. **`vkQueueSubmit2` (Vulkan 1.3) was unwrapped.** Modern wgpu uses this exclusively when available; the pre-1.3 `vkQueueSubmit` codepath was the only hook. Added `gpa_QueueSubmit2KHR` (handles both the core and KHR-aliased entrypoints).

3. **Indirect draws were unwrapped.** Added `gpa_CmdDraw{,Indexed}Indirect{,Count}` wrappers + KHR/AMD aliases. None of these fire on NVIDIA in this run, but they're real product-needed hooks.

4. **`vkCmdBeginRendering` (Vulkan 1.3 dynamic rendering) was unwrapped.** Added.

5. **SHM slot layout mismatch.** The Vulkan capture path wrote the GL header (width, height) + color pixels and went straight to draw-call metadata. The engine's parser (`engine.cpp::ingest_frame`) expected a depth section between color and metadata (GL convention), so the parser read garbage from the offset where draws should have been. Fixed by zero-filling a depth section in the Vulkan layer.

6. **GL-format draw call serialisation.** The Vulkan layer wrote a 44-byte-per-call format; the engine parser expected ~96 bytes/call (GL fields). Now serialises in GL-compatible shape with Vulkan's data in matching slots.

7. **`gpa_CmdExecuteCommands` was unwrapped.** Added a wrapper that harvests draws from the secondary cmd buffers it executes, since those draws belong to the executing primary's frame.

These are real product improvements the layer needed regardless of
the agent eval.

## What's still needed

For the layer to be honest evidence for the agent eval, we need to
identify and intercept whatever NVIDIA Vulkan path wgpu uses for
mesh draws on this configuration. Options:

- Install `VK_LAYER_LUNARG_api_dump` (requires sudo) to log every
  Vulkan call by name and signature, then add the missing entry
  points to our layer.
- Or build a minimal "trace everything" layer that wraps
  `vkGetDeviceProcAddr` and logs every resolved name, including
  dlsym-backed symbols loaded outside the layer chain.
- Or use Mesa's `lvp` (lavapipe) ICD instead of NVIDIA — wgpu
  reaches our layer fully on the lavapipe path (saw a
  short-lived run with `harvested=2` per submit), but the run
  itself isn't stable in our Xvfb config.

## Status of the agent eval

The earlier round-14 plan called for re-running the 6 missed
scenarios in `with_gla` mode against real captures, with the goal
of lifting the 33% code_only baseline to 60+%. That experiment is
**parked** until the Vulkan layer captures the full Bevy draw
stream on at least one ICD configuration we can run reliably
end-to-end.

What we *did* learn: synthetic captures are not a usable
substitute. Two pre-flight smoke tests (with hand-crafted Tier 1
state for #2 and #4, derived from each scenario's user report) did
*not* lift the agent's pick:

- #2 invisible_after_material_swap: agent picked
  `crates/bevy_pbr/src/material.rs` (same as code_only) instead of
  the real `crates/bevy_pbr/src/render/mesh.rs`. Reasoning was
  better — agent traced the `mark_meshes_as_changed` →
  `extract_mesh_materials` chain — but landed on the wrong end of
  it.
- #4 meshes_disappear_camera_motion: agent picked a WGSL shader
  (`build_indirect_params.wgsl`) instead of
  `crates/bevy_render/src/render_phase/mod.rs`, despite the
  synthetic capture explicitly stating the count buffer was last
  written by CPU upload, not GPU compute.

So the value-add experiment requires real captures. Real captures
require a more complete layer. The layer is the bottleneck.

## Reproducibility

- Bevy example: `examples/3d/r14_invisible_swap.rs` and
  `examples/3d/r14_control_no_swap.rs` in the `bevyengine/bevy`
  snapshot at `95b9117eac34`.
- Build:
  `CARGO_TARGET_DIR=/data3/cargo_target/r14_bevy_invisible_swap RUSTFLAGS="--cap-lints=warn" cargo build --example r14_invisible_swap --no-default-features --features "std,async_executor,bevy_asset,bevy_color,bevy_core_pipeline,bevy_pbr,bevy_render,bevy_window,bevy_winit,bevy_log,multi_threaded,x11,default_font,tonemapping_luts,bevy_state"`
- Run: `/tmp/run_bevy_under_gpa.sh` (sets up engine + Xvfb + layer
  dir + invokes the Bevy binary; queries REST endpoints when
  done).
