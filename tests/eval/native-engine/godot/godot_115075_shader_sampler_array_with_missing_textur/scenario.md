# R24: Godot sampler2D array with unassigned slots silently reuses another texture

## User Report
### Tested versions

- Reproducible in: v4.5.1.stable.official [f62fdbde1]

### System information

Godot v4.5.1.stable - Windows 11 - Vulkan (Forward+) - NVIDIA GeForce RTX
4070 Laptop GPU - Intel(R) Core(TM) i7-14650HX

### Issue description

If you create an array of `sampler2D` in a shader, but don't assign all
values, the last one is repeated:
```gdshader
shader_type spatial;

const float CUTOFF = 1.0;
const int N = 3;
uniform vec2 offset[N];
uniform sampler2D holes[N] : filter_nearest, repeat_disable;

void vertex() {}

void fragment() {
    float mask;
    mask = texture(holes[0], UV + offset[0]).r;
    mask *= texture(holes[1], UV + offset[1]).r;
    mask *= texture(holes[2], UV + offset[2]).r;
    if (mask < CUTOFF){
        discard;
    }
}
```

As you can see, when not all slots of `holes` are assigned, the last one is
repeated.

In addition, if values are restored to default: the array is empty, whereas
the `offset` is not empty and with default values.

I think the expected behaviour should be an error, not repeating.

### Steps to reproduce

Create a shader with an array of `sampler2D` and don't assign all textures.
Do something in the shader with the textures and the last one will be used
for all unassigned slots.

## Expected Correct Output
Either a shader/material validation error when the sampler array is not
fully populated, or a well-defined fallback (e.g. the engine's 1x1 white
texture) for unassigned slots — matching the behaviour of the POD
`offset[N]` array which retains defaults.

## Actual Broken Output
Unassigned `holes[i]` slots sample the same texture as an assigned slot
(appearing to "repeat the last one"), so the discard mask is computed from
the wrong data. The minimal GL repro reproduces the same class of pattern:
`holes[2]` is never given an explicit `glUniform1i()` binding, so it
defaults to sampler value 0 and reads from texture image unit 0 (red)
instead of unit 2 (blue) — the right third of the quad shows red pixels
where blue was expected.

## Ground Truth
The upstream thread contains the reporter's observation but no maintainer
root-cause analysis or linked fix. The reporter documents the symptom:

> If you create an array of sampler2D in a shader, but don't assign all
> values, the last one is repeated

and separately observes an asymmetry versus POD arrays:

> The array is empty, whereas the offset is not empty and with default
> values.

The reporter also states their expectation:

> I think the expected behaviour should be an error, not repeating.

No maintainer has identified whether the root cause lives in Godot's
shader-uniform binding path (e.g. missing `glUniform1i()` / descriptor
write for unassigned array elements, leaving the sampler at its default
binding of 0), in the material editor's serialization of partial sampler
arrays, or in driver behaviour for unbound sampler uniforms. The minimal
GL repro corresponds to the "missing `glUniform1i`" hypothesis: by GL spec,
an unassigned sampler uniform has value 0, so every un-bound array element
samples texture unit 0 — which in a typical Godot material bind order
happens to coincide with "whichever texture was bound last to unit 0",
matching the "last one is repeated" symptom.

## Difficulty Rating
3/5

## Adversarial Principles
- silent_uniform_default
- sampler_array_partial_binding
- missing_validation_error

## How OpenGPA Helps
Querying the draw call's uniform state shows `holes[0]=0`, `holes[1]=1`,
and `holes[2]=0` (the GL default) — the missing explicit binding for
index 2 is directly visible. Cross-referencing with the bound textures on
each image unit makes it obvious that slot 2 is reading unit 0's texture
rather than unit 2's, converting a puzzling visual artefact into a concrete
"this uniform was never assigned" fact.

## Source
- **URL**: https://github.com/godotengine/godot/issues/115075
- **Type**: issue
- **Date**: 2026-04-19
- **Commit SHA**: (n/a)
- **Attribution**: Reported on godotengine/godot#115075

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
  program_uniforms:
    - name: "holes[0]"
      expected_int: 0
    - name: "holes[1]"
      expected_int: 1
    - name: "holes[2]"
      expected_int: 2
      actual_int: 0
      note: "unassigned sampler array slot defaults to texture unit 0"
```

## Predicted OpenGPA Helpfulness
- **Verdict**: yes
- **Reasoning**: The root cause (a specific sampler array element never
  received an explicit `glUniform1i()` binding) is exactly the sort of
  fact a raw-uniform-state query exposes, while being nearly invisible
  from screenshots of the broken frame alone.

## Observed OpenGPA Helpfulness
- **Verdict**: ambiguous
- **Evidence**: validation skipped (--no-validate)
