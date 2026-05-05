You are an expert user of {framework} helping diagnose a config
mistake. The bug below is caused by a setting/flag the user did not
enable (or enabled incorrectly); the fix is a one-line configuration
change, not a code change.

# Bug report

{user_report}
{scope_hint_block}

# Resources

- Framework source at {upstream_snapshot.repo}@{upstream_snapshot.sha},
  accessible via Read / Grep / Glob. Consult to confirm the setting
  exists and its documented default.
<!-- WITH_GPA_ONLY -->
- OpenGPA live capture. `gpa report --frame latest --json` shows the
  captured GL state; the wrong config often surfaces as a specific
  pipeline-state anomaly.
<!-- END_WITH_GPA_ONLY -->

# Task

Identify the configuration key and its correct value. Cite the
framework file(s) where the setting lives (e.g.
``src/render/Renderer.ts``) — the harness scores you partly on those
file-level cites.

If, while reading the source, you discover the bug is actually
framework-internal (renderer/state/shader code, not a setting), switch
to the maintainer schema (`bug_class:"framework-internal"`,
`proposed_patches:[{repo,file,change_summary}]`) instead — mining
sometimes mis-classifies these.

# Output (REQUIRED — last line)

End with a SINGLE JSON object on the LAST line. No markdown around it.
Skipping the JSON means your diagnosis cannot be parsed — emit it
even if your confidence is low.

```
{
  "bug_class": "user-config",
  "setting_change": {
    "key": "<setting name, e.g. renderer.physicallyCorrectLights>",
    "value": "<correct value>",
    "context": "<where the user sets this, e.g. renderer init>"
  },
  "confidence": "high|medium|low",
  "reasoning": "short explanation of how you identified the setting"
}
```
