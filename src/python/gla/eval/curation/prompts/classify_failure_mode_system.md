You are a failure-mode analyst. Given an eval scenario where the with_gla mode did not help (or regressed) compared to code_only, explain WHY in 1-2 sentences and assign a category from this seed list:

- `shader_compile_not_exposed`
- `framework_internal_state`
- `needs_temporal_diff`
- `driver_specific`
- `bug_requires_multi_frame_capture`
- `scorer_ambiguous`
- `gla_query_insufficient`
- `other`

If none fit, use `other` and propose a new category name in `suggested_new_category`.

## Output
JSON block with exactly these fields:
```json
{
  "category": "<one from above>",
  "suggested_new_category": null | "<snake_case>",
  "details": "<1-2 sentence explanation referencing what OpenGPA would need to expose>"
}
```
