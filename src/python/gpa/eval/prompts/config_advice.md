You are an expert user of {framework} helping diagnose a config
mistake. The bug below is caused by a setting/flag the user did not
enable (or enabled incorrectly); the fix is a one-line configuration
change, not a code change.

# Output contract (READ FIRST — non-negotiable)

Your final message MUST end with a single, raw JSON object on its own
final line. Anything you say before that line is for your own reasoning;
the harness only scores what is in the JSON. If you skip the JSON your
diagnosis cannot be scored and the run is wasted.

```
{"bug_class":"user-config","setting_change":{"key":"<setting name>","value":"<correct value>","context":"<where the user sets this>"},"confidence":"high|medium|low","reasoning":"<short>"}
```

Rules for the JSON object:

- It must be the LAST non-empty line. Nothing after it — no signoff, no
  markdown fence, no trailing prose.
- It must be valid JSON: double-quoted keys/strings, no comments, no
  trailing commas.
- If you cannot pin the setting confidently, still emit the JSON with
  `value: ""` and `confidence: "low"` — never omit it.

If, while reading the framework source, you discover the bug is
actually in framework code (not user config), set `bug_class:
"framework-internal"` and emit `proposed_patches` (list of
`{repo,file,change_summary}` objects) instead of `setting_change` —
mining sometimes mis-classifies these.

# Bug report

{user_report}

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

Identify the configuration key and its correct value (or, if it turns
out to be framework-internal, the fix file), then emit the JSON object
described above as your final line.
