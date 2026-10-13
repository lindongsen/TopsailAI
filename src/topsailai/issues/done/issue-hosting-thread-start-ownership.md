---
maintainer: AI
author: DawsonLin
---
# Hosting startup interruption loses supervisor ownership

Status: pending
Severity: high

Independent review confirmed that workspace/plugin_instruction/hosting.py lines 61–68 treats thread.ident is None as proof no thread was launched. Thread.start may be interrupted while waiting for bootstrap publication after creating its native thread. The controller then clears its slot without requesting stop; close returns and unregisters the fallback. The delayed worker can subsequently launch a driver without session cleanup ownership.

Reproduction: gate bootstrap before ident assignment; interrupt the start method's internal publication wait after native launch; catch interruption; close controller; release bootstrap. Observed slot dropped and launcher entered after close with its context still open. Probe worker was explicitly stopped/joined afterward.

Required fix: retain identity-bound cancellation and recovery ownership across uncertain start publication, establish actual completion before declaring close settled, and add the pre-ident-publication interruption regression. Existing post-return interruption test does not cover this window.

Review evidence: .task/code_20261014T030000_hosting-independent-review.md. gpt-sol planned, ds-coder implemented, gpt-astra reviewed; repair remains assigned through Manager.
