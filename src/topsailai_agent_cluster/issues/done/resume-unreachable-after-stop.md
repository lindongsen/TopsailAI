---
maintainer: AI
author: DawsonLin
---

# Resume was unreachable after stop

## Trigger

LIFE-06 in the live tmux manual test attempted `resume` from the owned session scope immediately after LIFE-05 had stopped that exact generation.

## Observed behavior

The provider process exited and fresh inventory no longer contained the session, but the CLI rejected resume before confirmation with `selected session ... was not found`. Endpoint admission also required every targeted operation to resolve a live generation, so `agent.resume` could never execute for a stopped TopsailAI session.

## Root cause

Resume reused the live-session freshness path intended for send, inject, interrupt and stop. TopsailAI correctly omits stopped sessions from live discovery while preserving a durable provider session that `workspace resume -s` can restore. The TUI and Endpoint therefore required mutually exclusive states: resume needed a stopped historical session, while preflight required that session to be live.

## Resolution

Resume now requires the selected opaque resource to have a durable mapping and to be authoritatively absent from a complete fresh adapter inventory both before and after confirmation. Endpoint admission accepts that proven absence only for `agent.resume`; a live target, incomplete observation, observation error or unknown mapping fails closed. Other targeted operations continue to require an exact live generation.

## Prevention

Regression tests cover absent execution, live-target rejection, observation-error rejection and a target reappearing during confirmation. LIFE-06 must also verify one new provider generation and live message exchange through tmux.
