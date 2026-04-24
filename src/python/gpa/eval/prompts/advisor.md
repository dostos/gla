You are an expert user of {framework} responding to a bug report on
Stack Overflow. The symptoms in the issue below are real, but the bug
is NOT in {framework} itself — the reporter is using the library
incorrectly. Your job is to identify the API misuse and tell them what
they should do instead.

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

Identify the API-misuse pattern and describe the correct usage.

# Output (REQUIRED)

End with a SINGLE JSON object on the LAST line. No markdown around it.

```
{
  "bug_class": "consumer-misuse",
  "user_code_change": {
    "api": "<name of the {framework} API the user misused>",
    "correct_usage": "<1-2 sentences on what the user should do instead>"
  },
  "confidence": "high|medium|low",
  "reasoning": "short explanation of how you identified the misuse"
}
```
