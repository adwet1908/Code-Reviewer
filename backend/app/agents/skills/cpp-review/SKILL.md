---
name: cpp-review
description: C/C++ review checklist appended to reviewer and critic prompts.
model_tier: cheap
---

## C++ checklist
- Buffer overflows / unsafe `strcpy`, `sprintf`, fixed arrays vs string length (null terminator).
- Uninitialized members or locals used before assignment.
- Iterator invalidation after `erase` / container mutation in a loop.
- Null / nullptr checks on lookup results (`find*`, map access) before dereference.
- Leaks and raw owning pointers (`new` without matching `delete` / prefer smart pointers).
- Off-by-one limit checks (`>` vs `>=` on counts and capacities).
- Swapped argument order at call sites vs callee signature.
- Missing input validation on IDs, sizes, and public API arguments.
- Use-after-free and dangling references from erased elements.
