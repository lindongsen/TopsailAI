---
maintainer: AI
author: DawsonLin
---
# Object namespace nesting

Creating a parent over a classification directory containing an existing object can invoke payload replacement over the child tree. Per-object locks do not coordinate distinct IDs. Serialize manager create/move namespace changes, validate ancestors, and reject nonempty destinations before any mutation. Verify preservation with isolated tests. Runtime layout cutover remains a separate task.
