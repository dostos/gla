# R211: PlayCanvas fog renders in front of closer objects on certain Macs (glBlitFramebufferCHROMIUM depth/stencil format mismatch)

## User Report
On very specific Mac devices a WebGL error shows up when using fog effects in PlayCanvas. Visually, it causes the fog to render in front of objects that are closer to the camera, when it should be behind them. So far this has only been seen on a device running OS X 10.13. The issue reproduces on both Safari and Chrome on that machine, so it looks like a hardware/driver support issue rather than a browser bug.

Error printed in Chrome on OS X 10.13:

```
[.WebGL-0x7fba65070000]GL ERROR :GL_INVALID_OPERATION : glBlitFramebufferCHROMIUM: src and dst formats differ for depth/stencil
```

A minimally reproducible project was not produced — most Mac devices are unaffected and the reporter had trouble finding a second device to test on. Reporter suspects this is a hardware-support edge case in how PlayCanvas configures its render-target depth/stencil attachments versus the default framebuffer's depth/stencil format.

## Expected Correct Output
Fog should render *behind* objects that are closer to the camera, with no WebGL error logged to the console.

## Actual Broken Output
Fog renders *in front of* objects that are closer to the camera (depth ordering is wrong for the fog pass), and the console emits `GL_INVALID_OPERATION : glBlitFramebufferCHROMIUM: src and dst formats differ for depth/stencil` once per frame on the affected machine.

## Ground Truth
The issue (https://github.com/playcanvas/engine/issues/2425) was closed without a fix PR being identified. The reporter could not produce a minimal reproduction, a maintainer asked for a Firefox log to get a more descriptive error, and after over a year of inactivity another maintainer closed the issue:

> This issue seems to have gone stale, having not been updated in over a year. [...] macOS has moved on in the interim so perhaps this is no longer a problem? Anyway, due to the age of the issue, I'll close for now (although happy to reopen).

The diagnostic signal in the thread is the `glBlitFramebufferCHROMIUM` error itself: Chrome's CHROMIUM blit extension requires that the source and destination framebuffers have matching depth/stencil attachment formats. The wrong fog ordering is the visible symptom of the failed depth blit — when the blit errors out, the depth buffer used by the fog pass is not what the engine expected, so depth comparisons against the fog quad go the wrong way. No upstream patch landed, so this scenario is preserved as a legacy bug-pattern reference rather than as a localizable fix.

## Fix
```yaml
fix_pr_url: (none — issue closed stale, no fix PR identified)
fix_sha: (n/a)
fix_parent_sha: (n/a)
bug_class: legacy
framework: playcanvas
framework_version: (unspecified — issue filed against PlayCanvas engine on OS X 10.13, ~2020)
files: []
change_summary: >
  Fix PR not resolvable from the issue thread alone; the report was closed
  stale after the reporter could not produce a minimal reproduction and
  no maintainer landed a patch. Scenario retained as a legacy bug-pattern
  reference for depth/stencil format-mismatch errors during framebuffer
  blits in WebGL frameworks.
```

## Flywheel Cell
primary: framework-maintenance.web-3d.depth-stencil-mismatch
secondary:
  - framework-maintenance.web-3d.driver-edge-case-triage

## Difficulty Rating
4/5

## Adversarial Principles
- bug-lives-inside-framework-not-user-code
- diagnosis-requires-gl-error-stream-not-pixel-comparison
- driver-specific-symptom-not-reproducible-on-most-hardware
- visible-symptom-and-error-message-have-non-obvious-causal-link

## How OpenGPA Helps
`gpa trace` would surface the offending `glBlitFramebuffer` call along with the source and destination framebuffer attachment formats side by side, making the format mismatch obvious without having to interpret the CHROMIUM-prefixed error string. `gpa report --gl-errors` would show the `GL_INVALID_OPERATION` correlated to that exact blit, and `/framebuffers/<id>` would list the depth/stencil attachment format of each FBO so the agent can see which side of the blit has the mismatched format.

## Source
- **URL**: https://github.com/playcanvas/engine/issues/2425
- **Type**: issue
- **Date**: 2020-09-23
- **Commit SHA**: (n/a — closed without fix)
- **Attribution**: Reported by @Christopher-Hayes; triaged by @mvaligursky and @willeastcott; closed stale without an identified fix PR.

## Tier
maintainer-framing

## API
webgl

## Framework
playcanvas

## Bug Signature
```yaml
type: code_location
spec:
  expected_files: []
  fix_commit: (none)
```

## Predicted OpenGPA Helpfulness
- **Verdict**: yes
- **Reasoning**: Even without a localizable fix, GPA's GL-error stream and framebuffer-attachment introspection would let an agent connect the visible fog-ordering bug to the failed depth/stencil blit — the exact diagnostic step the upstream thread was missing when the reporter could not get a more descriptive error from the browser. This is the kind of driver-edge-case triage that benefits from raw capture over user-side guessing.