---
name: generic-review
description: Language-agnostic checklist when no specific skill matches.
model_tier: cheap
---

## Generic checklist
- Null / missing value handling on lookups and optional returns.
- Resource lifetime and cleanup.
- Bounds and off-by-one errors.
- Argument order and type mismatches at call sites.
- Missing validation of external input.
- Concurrency / shared mutable state issues.
- Security: injection, path traversal, unsafe deserialization.
- Clear correctness bugs over style-only nits.
