You are a maintainer of {framework}. A user filed the issue below. You
have full read access to the {framework} repository at the pre-fix
commit.

# Output contract (READ FIRST — non-negotiable)

Your final message MUST end with a single, raw JSON object on its own
final line. Anything you say before that line is for your own reasoning;
the harness only scores what is in the JSON. If you skip the JSON your
diagnosis cannot be scored and the run is wasted.

```
{"bug_class":"framework-internal","proposed_patches":[{"repo":"{framework}","file":"<path inside framework repo>","change_summary":"<1-2 sentences>"}],"confidence":"high|medium|low","reasoning":"<short>"}
```

Rules for the JSON object:

- It must be the LAST non-empty line. Nothing after it — no signoff, no
  markdown fence, no trailing prose.
- It must be valid JSON: double-quoted keys/strings, no comments, no
  trailing commas.
- `proposed_patches[*].file` must be a path **inside the framework
  repo**, relative to its root. NOT `tests/...`, NOT the scenario dir,
  NOT `main.c`, NOT a URL.
- Cite at least one patch. If you genuinely cannot identify a fix file
  with any confidence, still emit the JSON with `proposed_patches: []`
  and `confidence: "low"` — never omit the JSON.

The bug lives in the {framework} framework source. Your fix MUST
propose a change to files inside the framework source tree. Do NOT
propose changes to test files, user application code, or the scenario's
minimal repro.

# Bug report

{user_report}

# Resources

- Framework source at {upstream_snapshot.repo}@{upstream_snapshot.sha},
  accessible via Read / Grep / Glob (or the harness-provided
  `read_upstream` / `list_upstream_files` / `grep_upstream` tools).
<!-- WITH_GPA_ONLY -->
- OpenGPA live capture. Prefer:
  - `gpa report --frame latest --json` — all diagnostics in one call.
  - `gpa trace value <literal> --json` — reverse-lookup framework fields
    whose value matches a captured uniform / matrix / texture ID.
    Especially valuable when the bug's symptom is a specific numeric
    value whose origin points at the fix.
  - `gpa check <name>` / `gpa dump <aspect>` for drill-down.
<!-- END_WITH_GPA_ONLY -->

# Task

Locate the bug, propose a concrete fix, then emit the JSON object
described above as your final line. Reasoning prose before the JSON is
welcome but not required — the JSON is what gets scored.
