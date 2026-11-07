---
maintainer: AI
author: DawsonLin
---
# Adapter-owned project launch

Human requested adapter handlers with provider-managed project selection, manual folders and initial tasks instead of static profiles. Previously the cluster required compatibility resource/profile/revision input and did not forward an initial task. Implemented live authenticated handler queries, revision-bound routing and literal task payload forwarding, preserving legacy explicit syntax. Verification and remaining limitations are tracked in the task plan. Project listing never mutates provider registrations. Known boundary: subprocess output is captured before byte-limit validation; provider launcher leading-option task handling requires provider-side integration verification. Real model completion was previously blocked by regional HTTP403 and is not inferred from submission.

Real tmux hello task consumption and model response succeeded. A separate observation that session-scoped logs returned an empty body was recorded and then dropped by human decision, so it is not tracked as an open issue.
