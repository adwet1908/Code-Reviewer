---
name: python-review
description: Python review checklist appended to reviewer and critic prompts.
model_tier: cheap
---

## Python checklist
- None dereference / missing guards on optional returns.
- Mutable default arguments.
- Resource leaks (files, sockets) without context managers.
- Incorrect exception handling that swallows errors or is too broad.
- Race conditions around shared state without locks.
- SQL / command injection from string formatting.
- Off-by-one and inclusive/exclusive slice mistakes.
- Wrong argument order or kwargs mismatch at call sites.
- Missing validation on external input (paths, sizes, auth).
