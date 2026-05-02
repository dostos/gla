# R4: Too dark edges due to new IBL multi-scattering approach

## User Report
After updating three.js from r104 to r113, fully glossy MeshStandardMaterial spheres lit only by an HDR environment map (IBL) show noticeably darker rims/edges than before. The dark fringe is visible on light, smooth materials and on rough dark materials alike — even occluded regions of dark fabric pick up an unexpected ring of darkening that wasn't present in r104.

Reproduction: load a sphere with `MeshStandardMaterial` (metalness ≈ 1, roughness ≈ 0–0.3) into a scene whose only light is an HDR EquirectangularReflectionMapping environment. Compare side-by-side against r104 and against a reference renderer (Arnold, BabylonJS) using the same envmap.

Versions tested: r113 (current at time of report), r104 (last "good" version). Reporter suspects something changed in IBL handling between r104 and r113. ACES Filmic tone mapping was eventually applied at a maintainer's suggestion, which softened but did not eliminate the rim darkening. A linked report (#18669) describes the same symptom as "energy loss at grazing angles" on a simple roughness=0/metalness=0 sphere.

## Expected Correct Output
Glossy/rough PBR spheres lit by an IBL environment should match a reference renderer's output reasonably closely — bright, energy-conserving rims that fade smoothly toward the silhouette. No characteristic dark band hugging the edge of the sphere.

## Actual Broken Output
A dark ring is visible at grazing angles on glossy materials. On rough dark materials the artefact reads as a stripe of unexpectedly-bright reflection in regions that should be fully diffuse. The shape of the artefact tracks the silhouette of the geometry, not the lighting, suggesting it comes from the BRDF evaluation rather than the environment data.

## Ground Truth
This issue stayed open from 2020 and was eventually closed in 2024 with the maintainer comment:

> The PBR material has been improved multiple times over the last years. The original reported "too dark edges " issue from 2020 isn't present in latest releases anymore.

No single fix PR resolves the bug. The multi-scattering approximation introduced around r105 (referencing the JCGT 2019 paper http://www.jcgt.org/published/0008/01/03/) was iteratively refined across many releases — there is no clean parent SHA that "is broken" and a single child SHA that "is fixed." Maintainer @elalish acknowledged in the thread:

> I'm really not sure, but frankly the multiscattering approach in three is pretty hard for me to follow and it definitely gives different results than Filament.

The fix is therefore distributed across years of incremental shader-chunk edits to the PBR pipeline, not isolatable to a reviewable PR.

Issue URL: https://github.com/mrdoob/three.js/issues/18569
Linked: #16409, #18669

## Fix
```yaml
fix_pr_url: (none — closed as "improved over time" without a single fix PR)
fix_sha: (none)
fix_parent_sha: (none)
bug_class: legacy
framework: three.js
framework_version: r113
files: []
change_summary: >
  Fix PR not resolvable from the issue thread alone; the multi-scattering
  IBL approximation was refined incrementally across many three.js releases
  rather than fixed in a single PR. Scenario retained as a legacy
  bug-pattern reference for IBL/BRDF rim-darkening artefacts.
```

## Flywheel Cell
primary: framework-maintenance.web-3d.code-navigation
secondary:
  - framework-maintenance.web-3d.captured-literal-breadcrumb

## Difficulty Rating
5/5

## Adversarial Principles
- bug-lives-inside-framework-not-user-code
- diagnosis-requires-shader-source-reading-not-pixel-comparison
- no-single-fix-commit-exists

## How OpenGPA Helps
`gpa trace` on the affected draw call surfaces the linked fragment shader source for the MeshStandardMaterial program; grepping that source for `BRDF_GGX`, `DFGApprox`, or `EnvironmentBRDF` lets the agent localize the multi-scattering term that produces the rim. `/uniforms` on the same draw call exposes the prefiltered environment samplers and roughness LUT bindings, confirming the artefact comes from BRDF math and not from a missing/miswired envmap.

## Source
- **URL**: https://github.com/mrdoob/three.js/issues/18569
- **Type**: issue
- **Date**: 2020-02-07
- **Commit SHA**: (none — no single fix commit)
- **Attribution**: Reported by @silvainSayduck; discussed by @WestLangley, @elalish, @jsantell; closed by maintainer in 2024 as "improved over time."

## Tier
maintainer-framing

## API
opengl

## Framework
three.js

## Bug Signature
```yaml
type: code_location
spec:
  expected_files: []
  fix_commit: (none)
```

## Predicted OpenGPA Helpfulness
- **Verdict**: partial
- **Reasoning**: GPA can surface the actual fragment shader source and uniform bindings driving the artefact, which is genuinely useful for localizing the multi-scattering term. But because no canonical fix exists, "helpfulness" reduces to "did the agent identify the BRDF chunk responsible" — a softer scoring target than a code_location match against a real fix PR.

## Observed OpenGPA Helpfulness
- **Verdict**: ambiguous
- **Evidence**: validation skipped (--no-validate)
