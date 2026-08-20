---
maintainer: AI
workspace: /TopsailAI/src/topsailai
ProjectFolder: /TopsailAI/src/topsailai
ProjectRootFolder: /TopsailAI
ProjectCode: TOPSAILAI
programming_language: python
---

# Orphaned terminal input helper consumes a CPU core

## Symptom

A terminal-input helper could remain alive after its parent exited and spin at full CPU after its PTY became invalid.

## Root cause

`utils/input_tool.py::_spawn_terminal_input_subprocess()` armed its alarm only when an input timeout was configured. With no timeout, an orphaned helper blocked in GNU readline indefinitely; a deleted PTY could cause readline to repeatedly observe readability followed by terminal `EIO` errors.

## Resolution

The helper now records its expected parent PID and runs a one-second watchdog when input has no finite timeout. The watchdog exits when the parent changes or stdin no longer supports terminal access, while preserving the existing finite-timeout behavior.

## Verification

Focused unit tests verify termination after a parent PID change and after terminal validation fails. The complete input-tool unit test file passes.
