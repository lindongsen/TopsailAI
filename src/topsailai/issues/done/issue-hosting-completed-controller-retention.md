---
maintainer: AI
author: DawsonLin
---
# Completed hosting controllers remain rooted by atexit

Status: pending
Severity: medium

The callback registered by HostingController.start in /TopsailAI/src/topsailai/workspace/plugin_instruction/hosting.py:54-56 retains the controller strongly. Natural completion at lines 124-126 publishes done but does not retire this registration. Only close at lines 160-162 unregisters it; the instruction has deliberately no close lifecycle. Dropping completed instruction callbacks therefore leaves each controller, last launch, process object and potential exception traceback reachable until interpreter exit. Repeated instruction instances accumulate retained objects and shutdown callbacks without a bound.

Reproduction: create three controllers with a context-managed already-completed child, start each, await done and join its worker, retain only weakrefs, and force GC. All three remain reachable with _exit_registered=True. Explicitly invoking the internal controller close releases all three. This probe avoids external LLM and live sessions.

Required fix: retire exit-hook ownership when the exact launch is fully settled, with synchronization against restart so an older worker cannot unregister a newer launch's safety callback; preserve fallback ownership for uncertain startup and unresolved cleanup. Do not restore HookInstruction.close or session-end cleanup. Add regression coverage for discarded completed callbacks/controllers, repeated instances, restart races and unresolved ownership.

Evidence: /TopsailAI/src/topsailai/.tmp/hosting-full-review/probe.log
Review report: /TopsailAI/src/topsailai/.task/code_20261014T035905_hosting-full-review.md
