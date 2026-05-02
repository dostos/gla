# R14: Godot DrawableTexture2D resize then blit_rect produces wrong results

## User Report

The reporter is using a `DrawableTexture2D` to assemble a runtime
texture. After calling `setup(width, height, ...)` on it and then
calling `blit_rect(Rect2i(0, 0, width, height), ...)` once, the
texture preview looks correct.

Then they call `set_width(new_width)` and `set_height(new_height)`
to resize the drawable, followed by `blit_rect(Rect2i(0, 0,
new_width, new_height), ...)` — the second blit shows visibly
wrong output: the preview tile looks stretched, sliced, or
otherwise mangled relative to the source image they passed in.

The reporter discovered by experimentation that calling the second
`blit_rect` with the *original* (pre-resize) width/height
"produces the expected result", which suggested the resize did
not actually take effect inside the drawable's underlying state
even though the public API accepted it.

Repro (4.7-dev3):
1. Create a `DrawableTexture2D` and call `setup(w, h, ...)`.
2. Call `blit_rect(Rect2i(0, 0, w, h), ...)`.
3. Call `set_width(new_w)` and `set_height(new_h)`.
4. Call `blit_rect(Rect2i(0, 0, new_w, new_h), ...)`.
5. Compare the two preview outputs — the second one is wrong.

## Expected Correct Output

Either `set_width`/`set_height` should produce a correctly-sized
backing texture so a subsequent `blit_rect` with the new
dimensions writes the source image exactly, **or** those setters
should be removed and the user pointed at `setup()` for resize.

## Actual Broken Output

After `set_width`/`set_height`, the drawable's exposed width/height
report the new values (so the user sizes their `Rect2i` to match),
but the underlying GPU texture was not actually re-allocated to
those dimensions. The driver writes the new larger Rect2i into the
old smaller texture, which produces wrap-around / clipped /
distorted output in the preview.

## Ground Truth

Per the fix PR ("Remove `set_width` and `set_height` from
DrawableTexture since they are not functional"):

> The fundamental problem with set_width/height is that to set both,
> you end up recreating the texture twice ... Further, the API
> encourages you to frequently change width/height which is a very
> expensive operation. The reason to expose them is to allow users
> to easily change width/height (instead of having to call `setup(`).

The fix removes the broken `set_width`/`set_height` setters from
`DrawableTexture2D` entirely and steers users toward `setup()`,
which correctly recreates the underlying texture. Documentation
is updated to point at the right API.

See https://github.com/godotengine/godot/pull/118535 (fixes
#118178).

## Fix
```yaml
fix_pr_url: https://github.com/godotengine/godot/pull/118535
fix_sha: 8e303ff6d930f8e82feb209e54606620d031cf4b
fix_parent_sha: d1f2007d495426d140c4cecea3cf406b50c1679d
bug_class: framework-internal
framework: godot
framework_version: 4.7-dev3
files:
  - scene/resources/drawable_texture_2d.cpp
  - scene/resources/drawable_texture_2d.h
change_summary: >
  `DrawableTexture2D::set_width` and `set_height` updated the
  cached width/height fields without actually re-allocating the
  underlying GPU texture. Subsequent `blit_rect` calls used the
  new dimensions when computing destination coordinates but wrote
  into the old (smaller) backing texture, corrupting output. The
  fix removes both broken setters; users must use `setup(w, h, ...)`
  for resize, which correctly creates a fresh backing texture.
```

## Upstream Snapshot
- **Repo**: https://github.com/godotengine/godot
- **SHA**: d1f2007d495426d140c4cecea3cf406b50c1679d
- **Relevant Files**:
  - scene/resources/drawable_texture_2d.cpp
  - scene/resources/drawable_texture_2d.h

## Flywheel Cell
primary: framework-maintenance.game-engine.code-navigation
secondary:
  - framework-maintenance.game-engine.captured-texture-dimension-mismatch

## Difficulty Rating
3/5

## Adversarial Principles
- bug-lives-in-resource-class-not-renderer
- inconsistent-state-between-public-property-and-gpu-resource
- visible-symptom-only-on-the-second-blit-after-resize

## How OpenGPA Helps

A capture taken on step 4 would record the destination texture's
actual GPU dimensions at the time of `blit_rect`. The Python
binding's texture metadata would show width/height that *don't*
match the `DrawableTexture2D.width`/`height` properties, exposing
the desync between the resource's reported size and its real
backing storage. Once the agent sees "the GPU thinks this texture
is W×H but the engine reports W'×H'", they can grep for code that
sets those properties without recreating the texture and land on
`drawable_texture_2d.cpp` rather than the renderer.

## Source
- **URL**: https://github.com/godotengine/godot/issues/118178
- **Type**: issue
- **Date**: 2026-04-14
- **Commit SHA**: 8e303ff6d930f8e82feb209e54606620d031cf4b
- **Attribution**: Reported in godot#118178; fix in PR #118535.

## Tier
end-user-framing

## API
unknown

## Framework
godot

## Bug Signature
```yaml
type: code_location
spec:
  expected_files:
    - scene/resources/drawable_texture_2d.cpp
  fix_commit: 8e303ff6d930f8e82feb209e54606620d031cf4b
```

## Predicted OpenGPA Helpfulness
- **Verdict**: yes
- **Reasoning**: The user report names a specific API (`blit_rect`,
  `DrawableTexture2D`) but says nothing about the underlying
  cause. A code_only agent would inspect the API path and might
  reach the right file, but they'd have to read every relevant
  function. A capture-driven approach surfaces "the texture's
  real GPU dimensions don't match its reported width/height"
  almost immediately, narrowing the search to the resize
  pathway specifically.

## Observed OpenGPA Helpfulness
- **Verdict**: ambiguous
- **Evidence**: validation pending — code_only baseline not yet run.
