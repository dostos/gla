You are a maintainer of {framework}. A user filed the issue below. You
have full read access to the {framework} repository at the pre-fix
commit.

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

Investigate thoroughly. Locate the bug. Cite **every** framework file
you believe is involved in the fix — bugs in this domain typically
span 5-15 files (renderer + shader + storage + headers). Naming only
the most obvious file misses the surrounding refactor and the harness
will score you below threshold.

Write your reasoning in prose with concrete file paths inline like
``servers/rendering/foo.cpp:621``. Then end your response with the
output JSON below.

# Output (REQUIRED — last line)

End with a SINGLE JSON object on the LAST line. No markdown around it.
Skipping the JSON means your file-level signal cannot be parsed —
emit it even if your confidence is low.

```
{
  "bug_class": "framework-internal",
  "proposed_patches": [
    {
      "repo": "{framework}",
      "file": "<path inside framework repo, relative to its root>",
      "change_summary": "1-2 sentences: what to change and why"
    }
  ],
  "confidence": "high|medium|low",
  "reasoning": "short explanation of how you found the fix file"
}
```

Files MUST be paths inside the framework repo — NOT the scenario dir,
NOT `main.c`, NOT anything under `tests/`.
