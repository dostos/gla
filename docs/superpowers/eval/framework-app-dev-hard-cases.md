# Taxonomy-Aware Mining Plan

_Date: 2026-05-01_

## Process Summary

The improved mining flow is taxonomy-first:

1. `Discoverer` reads a YAML query config and fetches GitHub Issues/PRs and StackOverflow questions.
2. URL dedup uses `docs/superpowers/eval/coverage-log.jsonl`.
3. `run.py` fetches thread text and applies rules from `mining_rules.yaml`.
4. The planner emits taxonomy cells, bug-class guesses, score reason codes, and a stratified selected set.
5. Selected URLs flow into the deterministic extract_draft + commit DAG (no LLM).
6. The unified `run.py` orchestrator owns validation/commit.

The rules file makes the process generalizable beyond app-dev hard cases. It maps repos/tags to taxonomy cells, defines source-agnostic text patterns, and assigns scoring weights. Add new source adapters in Python, then classify their candidates through the same rules.

For `framework-app-dev`, the useful cases are not generic framework bugs. They are user-code/config mistakes where the wrong setting reaches GPU-visible state: draw order, depth/blend state, color encoding, render-target clears, shadow-camera bounds, or texture upload semantics. Prior runs show this is a low-yield slice: the broad framework corpus holds near 30% yield, while non-web-3d app-dev scout mining hit about 10%.

## Planner Command

Use:

```bash
PYTHONPATH=src/python python3 -m gpa.eval.curation.run \
  --queries src/python/gpa/eval/curation/queries/framework_app_dev_hard_cases.yaml \
  --rules   src/python/gpa/eval/curation/mining_rules.yaml \
  --max-phase select \
  --workdir .eval-pipeline
```

This is read-only against the production coverage log. The selected
candidates land in `.eval-pipeline/runs/<run_id>/journey.jsonl`. To
proceed end-to-end (extract + commit, no agent eval), drop the
`--max-phase` flag. To run the agent-eval measurement loop, add
`--evaluate`.

## Generating new queries

To explore scope NOT covered by previous runs, use `gen_queries` —
it reads the cross-run `scope-log.jsonl` and asks an LLM to propose
queries that bias toward unexplored repos:

```bash
PYTHONPATH=src/python python3 -m gpa.eval.curation.gen_queries \
  --instruction "WebGPU compute shader artifacts" \
  --scope-log .eval-pipeline/scope-log.jsonl \
  --out /tmp/new_queries.yaml \
  --max-queries 10 \
  --llm-backend claude-cli
```

Output is a draft YAML — duplicates against scope-log are filtered
out programmatically before the file is written, but near-duplicates
(same repo, similar keywords) still need a human eye. Pipe the
output into `gpa.eval.curation.run --queries ...` to mine the new
scope and append to scope-log.

## Rule Surface

The default rule file supports:

- `taxonomy.framework_repos`: maps GitHub repos to taxonomy sub-categories and framework names.
- `taxonomy.tag_frameworks`: maps StackOverflow tags or future source tags to cells.
- `patterns.visual`: observable user-visible symptoms.
- `patterns.gpu_state`: capture-visible state/config signals.
- `patterns.resolution`: accepted answers, maintainer resolutions, and fix links.
- `patterns.reject`: host-side or non-rendering signals.
- `scoring`: weights for each matched signal group.

## Candidate Seeds

| URL | Class | Why It Is Hard |
| --- | --- | --- |
| https://stackoverflow.com/questions/37647853/three-js-depthwrite-vs-depthtest-for-transparent-canvas-texture-map-on-three-p | user-config | Transparent points look solid/incorrect; accepted answer is depth testing vs depth writing. GPU capture can expose the depth-write/depth-test state directly. |
| https://stackoverflow.com/questions/72936071/srgbencoding-in-not-working-in-three-effectcomposer | user-config | EffectComposer output looks incorrectly encoded; answer is a final gamma/sRGB correction pass, not a framework patch. |
| https://stackoverflow.com/questions/74885977/three-js-show-srgb-colors-wrong | user-config | Generated canvas/SVG texture has wrong mid-tone colors; answer points to incomplete sRGB texture configuration. |
| https://stackoverflow.com/questions/65840482/how-to-avoid-background-image-from-turning-from-white-to-grey-when-using-tonemap | user-config | Background texture is tone-mapped unexpectedly; fix is app-side skybox/material config with `toneMapped: false`. |
| https://stackoverflow.com/questions/50444687/post-effects-and-transparent-background-in-three-js | consumer-misuse | Post-processing pass chain destroys transparent background; the symptom is framebuffer alpha/state visible even though the resolution is pass/material configuration. |
| https://stackoverflow.com/questions/72018834/shadows-in-react-three-fiber-working-but-cropped-in-rectangular-region-for-no-re | user-config | Cropped shadows look like renderer failure; answer is R3F/three.js shadow-camera bounds. |
| https://github.com/mrdoob/three.js/issues/31132 | user-config/browser-boundary | WebGPU/WebGL texture sampling differs for PNG metadata/premultiplied alpha; closed as browser/API behavior with app-side loader options/workarounds. |
| https://github.com/pmndrs/react-three-fiber/issues/2853 | adapter-boundary | Custom `WebGPURenderer` in R3F gives bad lighting with no console errors; good hard case for app/framework adapter diagnosis. |
| https://github.com/mapbox/mapbox-gl-js/issues/13229 | consumer-misuse/web-map | Dynamic GeoJSON update changes layer order; visible draw ordering is wrong after app data mutation. |
| https://github.com/mapbox/mapbox-gl-js/issues/10603 | legacy/web-map | Complex polygons render extra fills at some zooms; useful hard visual artifact but likely duplicate/legacy rather than clean user-config. |

## Keep/Reject Heuristic

Keep cases when the answer can be checked against captured state: a wrong draw order, depth/blend flag, framebuffer alpha, texture color-space/encoding, or shadow-map camera extent.

Reject cases when the "fix" is purely host-side and never reaches the GPU as wrong state: React lifecycle, event handlers, missing DOM/CSS sizing, TypeScript errors, or support questions where the rendered output was never wrong.
