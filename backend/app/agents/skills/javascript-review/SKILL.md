---
name: javascript-review
description: JavaScript/TypeScript review checklist for reviewer and critic.
model_tier: cheap
---

## JavaScript / TypeScript checklist
- Nullish access without optional chaining or guards.
- Async/await mistakes (missing await, unhandled promise rejection).
- Incorrect equality (`==` vs `===`) where coercion matters.
- Prototype / object injection from untrusted keys.
- XSS from unsanitized HTML insertion.
- Race conditions on shared mutable state.
- Off-by-one in loops and pagination.
- Wrong argument order at call sites; ignored TypeScript type mismatches that indicate bugs.
- Missing input validation on request bodies and query params.
