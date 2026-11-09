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

## A test can lock a defect in place by asserting the buggy behaviour

Trigger: the output-follow byte budget was ignored for the whole life of the feature, and the reason
it survived review was a test named `TestScanFollowLinesRejectsOversizedRecord`. That test asserted
that an oversized record produces an error, which is exactly the defect: the stream died instead of
truncating. The test was green, so the behaviour looked intentional and verified. The code comment
next to it claimed the record was "truncated and labelled", so the comment and the test disagreed and
nobody compared them.

Action: when a comment or document states an intended behaviour, check whether a test asserts that
same behaviour. If a test asserts something weaker or different, treat the disagreement as a defect
until proven otherwise, and read the test name critically: a name like `RejectsOversizedRecord`
records a decision, so confirm that decision was actually intended rather than inherited from the
first implementation. When fixing such a defect, replace the test rather than adding a new one beside
it, because the old test will otherwise keep asserting the old behaviour.

Why this prevents recurrence: a missing test leaves a gap that review might notice, but a wrong test
actively certifies the defect. It converts "nobody checked" into "somebody checked and approved",
which is far harder to detect later. Comparing the stated intent against the asserted intent is the
cheapest way to find this class of bug.

## A parameter threaded through every layer can still have no consumer

Trigger: `max_bytes` travelled from the CLI through the Server, the protocol struct and the Endpoint
into the adapter, and was then never read. Every layer forwarded it faithfully, so a review that
followed the plumbing saw a complete chain and concluded the feature worked. The snapshot path read
the same field correctly, which made the omission look even less likely.

Action: when verifying that a parameter works, do not stop at "it is passed everywhere". Find the
statement that actually consumes it and confirm the value changes observable behaviour. A grep for the
field name should show a read that affects output, not only assignments and struct literals. Prefer a
test that sets a distinctive value and asserts the effect, because a distinctive value cannot be
confused with a default.

Why this prevents recurrence: forwarding code is mechanical and easy to write correctly, so the
plumbing looks complete while the behaviour is absent. The defect is invisible in a diff review
because every changed line is correct; only the missing consumer is wrong, and a missing line does not
appear in a diff.

## A helper duplicated across two routes drifts

Trigger: the follow output route was fixed to truncate on a UTF-8 rune boundary, while the snapshot
route kept a raw byte slice. The same protocol field therefore produced valid UTF-8 on one route and
half a character on the other, and the snapshot defect survived because the only test guarding it
used an ASCII fixture that is valid UTF-8 at every byte offset.

Action: when the same logic is needed on two code paths, extract it into a package both paths already
import and have each path call it. A local wrapper that delegates is acceptable; a second copy is not.
When fixing one of two parallel paths, immediately check whether the sibling path has the same defect
instead of assuming the fix is local.

Why this prevents recurrence: a copied helper only postpones the divergence, because the next fix
lands on one copy and the other silently keeps the old behaviour. Sharing the implementation makes
the drift structurally impossible rather than dependent on someone remembering to change both. The
corollary is that a test whose fixture cannot express the failure mode is not coverage, it is a lock
on the current behaviour.

## A build failure in a file you never touched is not your defect

Trigger: while verifying a change to `internal/tui`, `go build ./...` failed twice in files this
task never edited — first `interactive_start_prompt.go` (a `writeStartHelp` arity mismatch), then
`launch_endpoint_choice.go` (a `launchAnswerValueOrControl` arity mismatch). Both were transient:
another agent was concurrently threading a `trustedOut` writer and a `ColorPolicy` through the same
package, so the call sites and the definitions disagreed for a few minutes. The same change had
already passed a full `go test ./internal/tui/` run minutes earlier.

Action: when a build or test failure names a file outside the current change set, check the file's
modification time against the files you edited before concluding anything. If it is newer, treat the
failure as a concurrent edit in flight: wait and re-run rather than editing that file. Never "fix"
another agent's half-applied refactor to make your own verification green, and never report the
failure as a defect in your own change. Confirm convergence by re-running the build until it is
clean, then run the full suite.

Why this prevents recurrence: a shared Go package has one compile unit, so any in-flight edit by a
concurrent agent surfaces as a failure attributed to whoever runs the build. Editing the foreign file
would collide with that agent's work and could silently discard its intent, and reporting it as your
own defect sends the review in the wrong direction. Timestamps distinguish "my change is broken" from
"someone else is mid-edit", and re-running is the only correct response to the latter.

## A styled prompt can be stripped by the writer, and a caller prompt can bypass the renderer

Trigger: the interactive `start.endpoint>` prompt had no colour while the REPL prompt did. Two
separate defects produced one symptom. `writeStartHelp` and the launch wizard built a styled prompt
and wrote it to the sanitizing writer, which strips SGR sequences, so the colour was emitted and
then discarded. Separately, `readPromptLine` used a caller-supplied prompt verbatim, so every caller
that passed a literal string opted out of styling entirely.

Action: when a styled string does not appear styled, check the writer before the style constant. A
sanitizing writer silently removes exactly the bytes that carry the styling, so the code looks
correct at the call site. Then check the choke point: if a shared read helper accepts a prompt
argument, style it there rather than at each call site, because a literal argument is an implicit
opt-out that no reviewer notices. Enumerate the actual read statements (`grep` for the read call,
not for the prompt text) to prove no path bypasses the helper.

Why this prevents recurrence: both defects are invisible in a diff. The styling call is present and
correct, and the prompt string is present and correct; only the writer or the argument path is
wrong, and neither shows up as a changed line. Counting the read statements converts "I fixed the
prompts I found" into "no input path can bypass the styling".

## Writing a prompt that the editor also draws prints it twice

Trigger: while colouring the endpoint-disambiguation question, the question was written to the
trusted writer and also passed to the read as its prompt. The terminal editor redraws the prompt it
is given, so in editor mode the question would appear twice. A stub reader that never writes the
prompt could not detect this, so the first probe passed and proved nothing.

Action: decide per prompt whether the caller or the editor owns the row. A named prompt is written
by the caller and the editor erases and redraws the same row, so it is safe. A question row carries
the editor's leading-newline marker, so the editor owns it and the caller must not write it. Verify
with the real editor, not a stub: drive `TerminalEditor.ReadLine` with a fake input and count the
occurrences in the captured output.

Why this prevents recurrence: a stub reader is a test double that omits the very behaviour under
test, so it certifies a duplication it cannot see. Counting occurrences in the real editor's output
is the only evidence that distinguishes "written once" from "written twice".
