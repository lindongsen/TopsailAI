# Learn

Lessons this project's AI learned from its own mistakes. Human-directed facts and decisions belong
in `MEMORY.md`, not here.

## Verify the producer of a value before claiming a defect is reachable

Trigger: while reviewing `StatusLabel`, the cluster-side mapping of `signal_sent` was found to be
operation-agnostic, and this was reported to the human as "send, interrupt and ctl actions can
display `stop request sent`". That claim was wrong. The real provider emits `signal_sent` from
`workspace kill` only; `runtime send` emits `pipe_written`, `runtime control` emits
`control_acknowledged`, and `runtime btw` emits `injection_queued`.

Action: before asserting that a defect is reachable, trace the value back to its producer and
enumerate every site that can emit it. For a cross-project boundary, read the producing project's
source, not only the consuming project's mapping. State reachability as "verified by producer
source at <path:line>" or mark it explicitly as unverified.

Why this prevents recurrence: the consuming side can only show which values it accepts, never which
values the producer actually sends. A mapping that looks operation-agnostic is not evidence that
every operation reaches it. Checking the producer converts a plausible inference into a fact, and
prevents reporting a latent design smell as an active user-visible bug.

## Do not infer a file convention from a sibling project without checking the intent

Trigger: the sibling `topsailai` project stores `MEMORY.md` as a symlink to `LEARN.md`, so the same
layout was copied here. The human rejected it: `LEARN.md` is what the AI learned, `MEMORY.md` is
what the human decided should be recorded. They are different audiences and must be different files.

Action: when copying a layout from another project, treat the layout as a local decision rather than
a shared convention. Ask what each file is for before mirroring it, and never collapse two documents
into one merely because a sibling project did.

Why this prevents recurrence: a symlink makes two names resolve to one document, so content written
for one audience silently appears in the other. The mistake is invisible in review because both
paths look correct.
