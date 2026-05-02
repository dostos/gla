---
name: gpa
description: Use when debugging an OpenGPA-captured graphics scenario via the gpa CLI.
---

See [docs/cli/agent-integration.md](../../../docs/cli/agent-integration.md) for the full guide.

Quick start:

```bash
gpa frames overview            # what's in the current frame
gpa drawcalls list             # list draw calls
gpa drawcalls explain --dc N   # deep dive on draw N
gpa pixel explain --x X --y Y  # which draw produced this pixel
gpa source read PATH           # read buggy app source
gpa upstream read PATH         # read upstream snapshot
```

GPA_FRAME_ID is set by the harness, so --frame is automatic.

Do not run pause/resume/step, annotations add, metadata set, or sources set unless asked.
