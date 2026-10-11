---
name: java-review
description: Java review checklist appended to reviewer and critic prompts.
model_tier: cheap
---

## Java checklist
- NullPointerException risks on returns and map lookups.
- Resource leaks (streams, connections) without try-with-resources.
- Concurrent modification of collections.
- Incorrect equals/hashCode contracts.
- Injection via concatenated SQL or commands.
- Off-by-one in loops and subList bounds.
- Swapped arguments at call sites.
- Missing validation on public API inputs.
- Ignoring interrupted exceptions or swallowing checked exceptions incorrectly.
