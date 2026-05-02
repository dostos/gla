# R212: Enabling autoGenerateMipmaps breaks filter screen sampling

## User Report
Using PixiJS 8.14.0 (Chrome 141 on Windows 11). When `PIXI.TextureSource.defaultOptions.autoGenerateMipmaps` is set to `true`, applying a filter that does scaled UV sampling (e.g. a pinch filter on a bunny sprite) produces a faded / corrupt result. The bunny appears to fade away rather than being pinched cleanly.

Reproduction is a CodeSandbox toggling that one default flag — nothing else changes. Without the flag the filter renders correctly; with the flag enabled the filter output sampling looks broken.

The reporter notes that as per a prior text-mipmaps issue there is no other way to enable mipmaps for `PIXI.Text` than to flip this default on, and that setting `PIXI.TexturePool.textureOptions.autoGenerateMipmaps = false` as a workaround also disables mipmaps for `Text`, since `TexturePool` is shared between filter render targets and text rendering. They want text mipmapping on and filter mipmapping off, which doesn't currently seem possible.

## Expected Correct Output
With `autoGenerateMipmaps` enabled globally, filters that sample their input render texture (such as a pinch filter applied to a sprite) should still produce visually correct, fully-opaque output — toggling the default mipmap flag should not affect filter rendering at all.

## Actual Broken Output
With the flag enabled, the filtered sprite fades / shows corrupt sampling. The pinch effect still distorts UVs but the sampled colors are wrong because the filter is reading from mip levels that were allocated but never populated with rendered content.

## Ground Truth
The PixiJS maintainer @vkarponen diagnosed the root cause directly in the issue thread:

> The actual fix should add mipmap setting into the ids generated for the pool so that it wouldn't use textures with mipmaps for filters.

In other words, `TexturePool` keys its pooled render textures by size/format but ignores the `autoGenerateMipmaps` flag. When the global default is flipped on, every pooled render texture is allocated with a full mip chain, but filters render only into mip level 0 and never call `generateMipmaps`. Filters then sample with derivatives that select higher mip levels, returning uninitialized texels — hence the "fade away" symptom.

The first community PR submitted (referenced in comment 4 by @doyoonear) was rejected by @vkarponen in comment 5 because it solved the symptom by globally disabling pool mipmapping, which regressed `PIXI.Text` mipmap generation — exactly the cross-cutting concern the original reporter called out via linked issue [#11304](https://github.com/pixijs/pixijs/issues/11304). The accepted fix shape is to include `autoGenerateMipmaps` in the pool's lookup id so `Text` and filter call sites get separate texture buckets.

The relevant code lives in PixiJS's shared texture pool — `src/rendering/renderers/shared/texture/TexturePool.ts` — specifically the id-generation path (`getOptionsHash` / pool key construction) used by `getOptimalTexture`. As of the issue filing no merged fix PR has been linked back to issue [#11717](https://github.com/pixijs/pixijs/issues/11717).

## Fix
```yaml
fix_pr_url: (none — issue open, only-submitted PR rejected by maintainer in thread)
fix_sha: (auto-resolve from PR — n/a)
fix_parent_sha: (auto-resolve from PR — n/a)
bug_class: legacy
framework: pixijs
framework_version: 8.14.0
files: []
change_summary: >
  Fix PR not resolvable from the issue thread alone; the only submitted PR
  was rejected by the maintainer for regressing PIXI.Text mipmapping. The
  maintainer-prescribed fix shape is to fold the autoGenerateMipmaps flag
  into TexturePool's pooled-texture key so filter and text call sites
  receive distinct buckets, but no merged commit yet. Scenario retained
  as a legacy bug-pattern reference.
```

## Flywheel Cell
primary: framework-maintenance.web-3d.code-navigation
secondary:
  - framework-maintenance.web-3d.captured-literal-breadcrumb
  - framework-maintenance.web-3d.cross-call-site-state-leak

## Difficulty Rating
4/5

## Adversarial Principles
- bug-lives-inside-framework-not-user-code
- shared-resource-pool-couples-unrelated-call-sites
- diagnosis-requires-grep-not-pixel-comparison
- symptom-is-sampling-from-uninitialized-mip-levels

## How OpenGPA Helps
A `gpa trace` on the broken frame shows the filter's draw call binds a render-target texture whose `GL_TEXTURE_MAX_LEVEL` / allocated mip count is greater than 0, while no `glGenerateMipmap` was ever called on that texture between the filter's render-into pass and its sample-from pass. That captured-state breadcrumb (mip levels allocated, mip levels never populated, sampler LOD bias / derivatives non-trivial) points the agent directly at the texture-pool allocation site rather than at the filter's shader — which is where a naïve agent without GPA state would start digging.

## Source
- **URL**: https://github.com/pixijs/pixijs/issues/11717
- **Type**: issue
- **Date**: 2026-04-27
- **Commit SHA**: n/a (no merged fix at time of capture)
- **Attribution**: Reported by the issue author against PixiJS 8.14.0; root-cause diagnosis by maintainer @vkarponen in comment 5; cross-referenced with linked text-mipmaps issue #11304.

## Tier
maintainer-framing

## API
opengl

## Framework
pixijs

## Bug Signature
```yaml
type: code_location
spec:
  expected_files:
    - src/rendering/renderers/shared/texture/TexturePool.ts
  fix_commit: (unresolved — issue open)
```

## Predicted OpenGPA Helpfulness
- **Verdict**: yes
- **Reasoning**: GPA's per-draw-call texture state reveals that the filter samples from a render target with an allocated mip chain but no `glGenerateMipmap` call in the frame, which immediately reframes the bug from "filter shader is wrong" to "input render texture was over-allocated by something upstream." That pivot points the agent at `TexturePool` rather than at the filter pipeline — which is the same pivot the maintainer makes in the thread.