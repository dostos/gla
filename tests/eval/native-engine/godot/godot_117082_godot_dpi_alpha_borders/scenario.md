# R14: Godot DPITexture has incorrect alpha borders

## User Report

In Godot 4.7-dev2, after importing some PNG art (with non-transparent
edges) as a `DPITexture` and dropping it on a `Sprite2D`, the user
sees a fairly clear black outline around the image whenever the
sprite isn't perfectly snapped to the viewport — i.e. when the editor
viewport is zoomed to a fraction or the sprite has a non-integer
position/offset/rotation/scale.

The same image imported as a regular `Texture2D` (right side of the
report screenshot) renders cleanly because `Texture2D` ships with a
sensible default for the import option that fixes alpha bleeding
along the image edge. The reporter notes that the option doesn't
exist on the `DPITexture` import dialog at all.

Repro:

1. Import a PNG as `DPITexture` and place it on a `Sprite2D` over
   a similarly colored background.
2. Zoom the editor viewport to a non-integer multiple, or set the
   sprite position to a non-integer value.
3. Observe the dark/black border around the sprite.

## Expected Correct Output

Imported `DPITexture` images render with the same edge fidelity as
`Texture2D`: when the sampler interpolates between an opaque pixel
on the inside of the image and a transparent (RGBA 0,0,0,0) pixel
just outside the image, the contributed RGB from the transparent
texel should match the inner pixel's RGB rather than fading toward
black.

## Actual Broken Output

Around the perimeter of the sprite, a 1-2 pixel dark outline shows
through, with intensity that varies depending on how close to a
pixel boundary the sprite is positioned. The outline is most
visible against backgrounds whose color is similar to the inner
edge of the texture.

## Ground Truth

Per the fix PR ("Add `fix_alpha_border` and `premult_alpha` to the
`DPITexture` importer"):

> Fixes https://github.com/godotengine/godot/issues/117082

The fix adds the `fix_alpha_border` import option (and
`premult_alpha`) to the `DPITexture` importer and runs the
fix-alpha-border post-processing during import, populating the
RGB channels of fully-transparent border texels with the color
of the nearest opaque pixel so that bilinear filtering doesn't
fade toward black. This was already the default for `Texture2D`
imports.

See https://github.com/godotengine/godot/pull/117088
(fixes #117082).

## Fix
```yaml
fix_pr_url: https://github.com/godotengine/godot/pull/117088
fix_sha: 2073a2bbd6bc4930dca3bfd725d58a4348bba2b6
fix_parent_sha: fe6f78a4c788e6a9fddb333d1cb467ee572262e8
bug_class: framework-internal
framework: godot
framework_version: 4.7-dev2
files:
  - scene/resources/dpi_texture.cpp
  - scene/resources/dpi_texture.h
  - editor/import/resource_importer_svg.cpp
change_summary: >
  The `DPITexture` import path lacked the `fix_alpha_border` option
  that `Texture2D` enables by default. Without it, fully-transparent
  pixels just outside the image keep their default RGB of (0,0,0),
  and bilinear filtering at the edge linearly blends those black
  RGB values into the visible inner pixels, producing a dark halo.
  The fix exposes `fix_alpha_border` (and `premult_alpha`) on the
  `DPITexture` importer and runs the same alpha-border fix-up so
  edge texel RGB is filled from the nearest opaque pixel.
```

## Upstream Snapshot
- **Repo**: https://github.com/godotengine/godot
- **SHA**: fe6f78a4c788e6a9fddb333d1cb467ee572262e8
- **Relevant Files**:
  - scene/resources/dpi_texture.cpp
  - scene/resources/dpi_texture.h
  - editor/import/resource_importer_svg.cpp

## Flywheel Cell
primary: framework-maintenance.game-engine.code-navigation
secondary:
  - framework-maintenance.game-engine.captured-texel-edge-color

## Difficulty Rating
3/5

## Adversarial Principles
- bug-lives-inside-asset-importer-not-renderer
- visual-symptom-only-vocabulary-in-user-report
- subtle-perimeter-artifact-easily-confused-with-correct-mipmapping

## How OpenGPA Helps

A capture of the rendered sprite would expose the texture-data
bound at draw time. By inspecting the bound texture's edge texels
(`/api/v1/textures/<id>/pixel?...`), the agent can see that
fully-transparent texels at the image perimeter have RGB = (0,0,0)
even though their adjacent inner texels are non-black. That single
fact directly identifies "alpha border was not fixed up at import
time" as the proximate cause, and the agent can search for the
import path that touched this texture (`DPITexture`) rather than
the renderer.

## Source
- **URL**: https://github.com/godotengine/godot/issues/117082
- **Type**: issue
- **Date**: 2026-03-11
- **Commit SHA**: 2073a2bbd6bc4930dca3bfd725d58a4348bba2b6
- **Attribution**: Reported in godot#117082; fix in PR #117088.

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
    - scene/resources/dpi_texture.cpp
    - editor/import/resource_importer_svg.cpp
  fix_commit: 2073a2bbd6bc4930dca3bfd725d58a4348bba2b6
```

## Predicted OpenGPA Helpfulness
- **Verdict**: yes
- **Reasoning**: The user report says nothing about importers,
  alpha channel handling, or texture filtering — only "black
  border around my sprite". A code_only agent has to guess
  whether to look in the renderer (sampler/shader) or asset
  pipeline (importer) — both are plausible. A frame capture
  reveals the bound texture's actual texel data, immediately
  showing that transparent edge texels have black RGB. That's a
  fact the user could not have known to mention, and it points
  past the renderer toward the importer.

## Observed OpenGPA Helpfulness
- **Verdict**: ambiguous
- **Evidence**: validation pending — code_only baseline not yet run.
