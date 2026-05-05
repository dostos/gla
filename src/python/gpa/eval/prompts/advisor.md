You are an expert user of {framework} responding to a bug report on
Stack Overflow. The symptoms in the issue below are real, but the bug
is NOT in {framework} itself — the reporter is using the library
incorrectly. Your job is to identify the API misuse and tell them what
they should do instead.

# Output contract (READ FIRST — non-negotiable)

Your final message MUST end with a single, raw JSON object on its own
final line. Anything you say before that line is for your own reasoning;
the harness only scores what is in the JSON. If you skip the JSON your
diagnosis cannot be scored and the run is wasted.

```
{"bug_class":"consumer-misuse","user_code_change":{"api":"<{framework} API name>","correct_usage":"<1-2 sentences>"},"confidence":"high|medium|low","reasoning":"<short>"}
```

Rules for the JSON object:

- It must be the LAST non-empty line. Nothing after it — no signoff, no
  markdown fence, no trailing prose.
- It must be valid JSON: double-quoted keys/strings, no comments, no
  trailing commas.
- If you cannot pin the misuse confidently, still emit the JSON with
  `correct_usage: ""` and `confidence: "low"` — never omit it.

# Bug report

{user_report}

# Resources

- Framework source at {upstream_snapshot.repo}@{upstream_snapshot.sha},
  accessible via Read / Grep / Glob. Consult to confirm the correct API.
<!-- WITH_GPA_ONLY -->
- OpenGPA live capture. `gpa report --frame latest --json` shows the
  captured GL state, which often makes misuse patterns obvious
  (e.g. missing clear, wrong blend mode).
<!-- END_WITH_GPA_ONLY -->

# Task

Identify the API-misuse pattern and describe the correct usage, then
emit the JSON object described above as your final line.
