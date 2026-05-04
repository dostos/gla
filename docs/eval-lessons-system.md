# Eval lessons — system improvements (round 12b audit)

## TL;DR

All 14 round-12b scenarios ran **snapshot-only** — `run.log` shows
`live capture unavailable` 14/14, so `GPA_FRAME_ID` was never set.
Yet `with_gla`'s prompt advertises 11 commands of which only 3
(`gpa upstream read|grep|list`) actually work. The agent worked
around the noise (web-map: 5/6 cited specific symbols) but the
prompt is miscalibrated, the upstream surface is grep-shaped (no
symbol-aware verbs, single-line matches), and the harness throws
away free signal (framework, fix-PR url, bug_class). Three
half-day fixes recover most of the win.

## 1. What the agent actually did

Sampled (`results.json`):

| scenario | tools | unique paths cited |
|---|---:|---|
| cesium camera_jumps (web win) | 53 | `Picking.js`, `Scene.js`, `GlobeTranslucencyState.js`, `ScreenSpaceCameraController.js` |
| deck.gl googlemapsoverlay (web loss) | 31 | `google-maps-overlay.ts` only |
| godot weird_shadow (godot win) | 22 | `scene_forward_mobile.glsl` |
| godot wrong_position_volumetric_fog (godot loss-by-scorer) | 36 | `render_forward_clustered.cpp`, `render_scene_data_rd.h`, `fog.cpp` |
| maplibre 3d_terrain (smoke win) | 20 | `painter.ts`, `draw_fill.ts` |

Agent did follow grep with read (cesium cites `Picking.js:66`
and `:595` — lines only knowable post-read) and chained list →
grep → read. **No sampled diagnosis references any non-`upstream`
gpa subverb** — `frames`, `drawcalls`, `pixel`, `scene`, `diff`,
`source` never used. Expected (no live frame), but ~75% of the
prompt's tool block was unusable. Deck.gl stuck to one file when
the fix may also touch viewport/transform plumbing —
*speculative*, no PR-diff verification.

## 2. Gaps in the gpa CLI surface for advisor use

Advisor mode = `upstream read|grep|list` only
(`src/python/gpa/cli/commands/upstream.py:28-56`). What's missing:

1. **No `gpa upstream find-symbol NAME`.** Agent grep'd
   `^Picking\.prototype\.update` to find a definition. A
   def-aware verb (per-language decl regex) is ~50 LOC.
2. **200 KB read cap too low** (`upstream.py:22`, `harness.py:29`).
   Cesium `Scene.js` is 164 KB (close); godot `rendering_device.cpp`
   369 KB, `shader_language.cpp` 402 KB exceed it. Sampled
   diagnoses didn't truncate (impact *speculative*) but the
   ceiling is wrong. Bump to 512 KB; add `--start-line/--end-line`.
3. **No bounded tree view.** `gpa upstream list` is one level only
   (`upstream.py:75-100`); the agent walked via repeated calls.
   `gpa upstream tree SUBDIR --max-depth N --max-entries M`
   replaces 3-5 list calls per scenario.
4. **No grep `--context`.** `grep_root_json` (`local_roots.py:139`)
   returns single 500-char lines, so the agent does a follow-up
   `read` for surrounding code. Add `before:`/`after:` arrays.
5. **No blame/history.** Snapshot is a real working tree
   (`harness._ensure_snapshot`); `gpa upstream blame PATH --line N`
   would orient the agent. *Speculative — no direct evidence in
   sampled traces.*
6. **Sanitised PR-context, not diff.** `gpa fix-pr show` would
   leak ground truth. Safe alternative: harness pre-strips
   fix-PR diff + description from the snapshot, then exposes
   `gpa upstream issue NUMBER` returning only the original issue
   text + repo metadata.

## 3. Prompt structure improvements

Current `gla_tools_block` (`cli_agent.py:80-96`) lists 11 commands
as bullets and ends with: `"GPA_FRAME_ID is set so --frame is
automatic."` That last line is **a lie 100% of the time** on
round 12b — `cli_agent.py:33-38` silently leaves `GPA_FRAME_ID`
unset when capture fails.

Proposed delta — switch on the harness signaling whether a
frame/snapshot is available:

```python
# cli_agent.py:80, after _build_tools sets _have_frame/_have_snapshot
if tools.get("_have_frame"):
    block = _LIVE_FRAME_BLOCK + _SNAPSHOT_BLOCK   # 11 bullets, current
elif tools.get("_have_snapshot"):
    block = (
        "Advisor mode: NO live frame for this scenario. "
        "Investigate via the upstream snapshot.\n\n"
        "- gpa upstream list [SUBDIR]   — orient\n"
        "- gpa upstream grep PATTERN    — find a symbol\n"
        "- gpa upstream read PATH       — read a match\n\n"
        "Typical loop: list → grep → read. Cite specific files.\n"
    )
else:
    block = _CODE_ONLY_BLOCK
```

Shorter, accurate, matches the shape of the agent's actual
behaviour.

## 4. Backend / harness ergonomics

1. **Tell the agent when the frame is missing.** Per §3 — the
   prompt currently asserts the opposite.
2. **Inject a scenario blurb.** `_render_prompt`
   (`cli_agent.py:73-113`) uses only `description` +
   `source_path`. It drops `scenario.framework`,
   `scenario.upstream_snapshot_repo`, `scenario.fix.fix_pr_url`,
   `tools["bug_class"]` — all already loaded. Prepend one line
   like `Scenario: godot bug in godotengine/godot
   (consumer-misuse). Issue: https://...`. Saves the first `list`
   call where the agent sniffs framework identity.
3. **"Session pollution" worry is unfounded.**
   `~/.claude/CLAUDE.md` 173 B, project `SKILL.md` 720 B, user
   `eval-driven-improvement/SKILL.md` 126 lines. Ambient skill
   context < 5 KB, not 32 K. **No action.**
4. **Eager snapshot fetch.** `cli_agent.py:46` calls
   `snap_provider()` immediately, cloning even if the agent
   never reads. Acceptable (cache reused), but a code-only
   rerun would save ~3 GB if this were lazy — leave for later.

## 5. Top three to ship first

1. **Snapshot-aware prompt branch + scenario blurb**
   (`cli_agent.py` + `harness.py`, ~40 LOC). Add
   `_have_frame`/`_have_snapshot` keys in `_build_tools`
   (`harness.py:215-298`); rewrite `_render_prompt`
   (`cli_agent.py:73-113`) per §3; prepend the blurb of §4.2.
   **Impact:** removes prompt noise on 100% of advisor runs;
   saves 1-2 turns from up-front framework knowledge.

2. **`gpa upstream grep --context N` + bump
   `_DEFAULT_MAX_BYTES` to 512 KB** (`upstream.py` +
   `local_roots.py`, ~30 LOC). Wire `-C N` through
   `grep_root_json` (`local_roots.py:97-148`); raise caps in
   `upstream.py:22` + `harness.py:29`. **Impact:** kills the
   grep→read follow-up visible in cesium/godot prose; ~5 fewer
   turns per godot run.

3. **`gpa upstream find-symbol NAME [--lang ...]`** (new file
   `cli/commands/upstream_symbol.py`, ~80 LOC). Language-specific
   decl regex; return top-5 matches with 10 lines of context.
   **Impact:** collapses list→grep→read into 1 verb for the
   most common opening move in every sampled diagnosis.
