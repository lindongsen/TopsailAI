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

## A restart-looping container can mean its bind mount is empty, not that the image is broken

Trigger: the server container was restart-looping with
`read CA certificate: open /etc/agent-cluster/certs/ca.pem: no such file or directory`.
The image was fine. `.tmp/docker/certs` was an empty directory, so the read-only bind
mount supplied nothing. The CA private key was absent from the project, so no new
certificate could be minted, and the obvious "regenerate the certs" fix was not
available.

Action: when a container fails on a missing file that should come from a mount, check
the host side of the mount before touching the image. Then search for an existing
artifact that already satisfies the trust relationship instead of minting new
credentials: verify the candidate certificate against the live CA, confirm the subject
and SAN match the identity the peer pins, and confirm the private key matches the
certificate by comparing public-key digests. Also match the file ownership to the
container's runtime uid, because a read-only mount still has to be readable.

Why this prevents recurrence: a missing mount looks identical to a broken image from
the logs, so rebuilding the image wastes time and changes nothing. Reusing a verified
existing certificate preserves the trust chain that the already-installed endpoints
depend on; minting a new CA would silently invalidate every deployed endpoint
certificate. Checking ownership avoids a second failure that looks like a TLS error but
is really a permission error.

## A protocol change on the server makes older endpoints look like a network fault

Trigger: after the server was restored, all three endpoints stayed `offline` while the
server logged `invalid hello attached`. The endpoints were healthy and reachable; they
were simply 56 commits behind and never sent the `hello_attached` confirmation frame
that the newer server requires (`internal/channel/server.go:164-172`).

Action: when endpoints fail to connect right after a server upgrade, compare the
installed endpoint version against the server build before investigating networking or
certificates. Read the rejection reason in the server log and locate the exact
validation site in the source, so the mismatch is proven rather than assumed.

Why this prevents recurrence: a handshake rejection is reported to the client as a
generic close frame, so the endpoint log only shows a reconnect loop and looks like a
transport problem. The server-side reason string is the only direct evidence, and
matching it to the validation site turns a guess into a fact. Upgrading the endpoints
is then the correct fix, and no network or TLS change is needed.

## A convenient data directory can be a symlink onto the filesystem that is already full

Trigger: the server database had to move off a 100% full root filesystem. The obvious
target `/opt/agent-cluster/data` looked correct because it sits under `/opt`, but it is a
symlink to `/var/lib/agent-cluster`, which is on the same full root filesystem. Copying the
database there would have changed nothing while appearing to fix the problem.

Action: before choosing a persistence location, resolve it with `readlink -f` and check the
filesystem of the resolved path with `df -h`, not the filesystem of the path as typed. A
directory that is a symlink is not a location, it is an alias for another location. Create a
real directory instead, and confirm the resolved path is the one that was created.

Why this prevents recurrence: `df` on the typed path follows the symlink and reports the
target filesystem, so the mistake is visible only if the resolved path is inspected
deliberately. A migration that silently lands on the same full filesystem looks successful
until the next write fails, and the failure then appears unrelated to the move.

## A connection generation kept only in memory makes a server restart look like a network fault

Trigger: after the server container was recreated, all three endpoints stayed `offline` and
reconnected every 10 seconds with `channel connection was superseded by a newer link`. The
network and certificates were fine. `Fence.Acquire` (`internal/channel/fencing.go:24-29`)
increments a generation held only in an in-memory map, so a restarted server starts again at
1, while the never-restarted endpoint still holds the higher generation it adopted before the
restart. `EndpointClient.Attach` (`internal/channel/endpoint.go:118-124`) then rejects every
new link because `c.Generation > generation`.

Action: when endpoints stop connecting right after a server restart, read the endpoint's own
rejection reason and locate the comparison in the source before investigating transport. If
the generation is not persisted, restart the endpoints as well, because only that clears the
in-memory value they are comparing against.

Why this prevents recurrence: the endpoint reports a reconnect loop and a broken pipe, which
looks exactly like a transport or TLS problem, so the real cause is invisible from the
symptom. The generation comparison is one-sided: the server has no memory of the value it
issued, so it cannot recognise the endpoint's value as stale. Restarting the endpoints is the
only recovery that does not require a code change, and the underlying defect remains until the
generation is persisted or renegotiated.

## Moving a conffile keeps the old file, so its stale comments survive the upgrade

Trigger: after the packaged configuration moved from `/etc/agent-cluster/node.conf` to
`/opt/agent-cluster/conf/node.conf`, both container endpoints kept a `node.conf` whose header
still said "conf, certs, data, logs and run are symlinks to the policy locations". dpkg had
correctly preserved the operator-edited conffile and written the new template beside it as
`node.conf.dpkg-dist`, so the shipped wording never reached the file in force.

Action: after changing a conffile path or its shipped content, inspect the installed file on every
node instead of assuming the package content is what is running. Compare it with the `.dpkg-dist`
sibling, and treat any surviving description of the old layout as a defect to fix in place. Fix the
site source that produced the file as well, otherwise the next rebuild reintroduces the stale text.

Why this prevents recurrence: a conffile is deliberately never overwritten, so an upgrade that
changes only comments looks successful while the running configuration still describes the previous
layout. The `.dpkg-dist` file is the only evidence that the package content differs, and it is easy
to mistake for leftover noise. Reading the installed file is what distinguishes "the package is
correct" from "the node is correct".

## A hardcoded output path is invisible until someone needs a different one

Trigger: the human asked for the package output directory to be configurable instead of hardcoded.
`Makefile` used `DEB_DIR := .tmp/deb`, and `scripts/make-deb.sh` hardcoded the staging tree as
`${PROJECT_DIR}/.tmp/deb/build`. The `:=` assignment was the real defect: it overrides an
environment variable, so `DEB_DIR=/srv/out make deb` silently wrote to `.tmp/deb` while the caller
believed the override took effect. Only a command-line assignment won, which is not what a
`VAR=value make target` caller expects.

Action: when a path is meant to be configurable, use `?=` so both the environment and the command
line can override it, and give every related path its own variable instead of deriving one from
another. Then check the whole target family, not only the build target: `deb-clean` still removed
`$(DEB_DIR)/build`, which stopped being the staging location the moment staging became independent,
so a clean after an override would have deleted the wrong directory and left the real staging tree
behind. Guard destructive targets against an empty value, because `rm -rf $(DEB_DIR)/build` with an
empty variable becomes `rm -rf /build`.

Why this prevents recurrence: a hardcoded default looks harmless because it works for the author's
own workflow, and `:=` versus `?=` is a one-character difference that no test exercises. The failure
is silent in both directions: the build succeeds into the wrong place, and the clean succeeds on the
wrong place. Verifying with `make -n` plus one real build into a throwaway directory is what turns
"the variable is used somewhere" into "the artifact actually landed there".

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

## A documented forwarding step can be absent from the launcher

Trigger: `docs/Environment_Variables.md` stated that the control action catalog path "is resolved
relative to the bundle root by the launcher", and `docs/agent-cluster-protocol.md` stated that the
catalog is "loaded at startup". Neither was true for a packaged node. `scripts/agent-clusterctl`
resolves `COMMAND_ALLOWLIST_FILE` and passes it as a flag, but it never reads `CONTROL_ACTION_FILE`,
so every packaged node started with no catalog and advertised zero `ctl.` actions while `node.conf`
named the file and the file existed with 48 entries.

Action: when a document says a component forwards, resolves or exports a value, verify that claim in
the component's source before trusting it, exactly as a defect claim is verified against its producer.
Search the launcher for the key name, not for the feature name: the feature was documented and the
template shipped the key, so a search for "control action" found documentation and configuration while
the missing line was a single absent `args+=` entry. Then confirm the runtime effect, because a
documented capability that silently degrades to fail-closed looks identical to a capability nobody
configured.

Why this prevents recurrence: documentation and configuration are written from intent, while the
launcher is written once and then extended key by key. A new key therefore lands in the template and
the docs but not in the launcher, and every test that guards the template stays green because the
template really is correct. The failure is fail-closed, so nothing unsafe happens and no error is
logged; the only symptom is an empty capability list that an operator reads as "not configured yet".
Comparing the documented forwarding list against the launcher's actual key list is what turns that
silent gap into a defect.

## An alias that also supplies a flag must not enter the alias registry

Trigger: `logf` was requested as a convenient spelling of `logs -f`. The first implementation
registered it in `commandAliases` as `"logf": "logs"`, which resolves the word but drops the flag:
`logf` would then parse an empty tail and render a one-shot snapshot. That is the worst outcome for
this command, because a snapshot presented as a stream looks complete while silently missing
everything written after it. The same entry also broke Tab completion: `completableCommands` collects
every multi-character alias, so `lo` became ambiguous between `logs` and `logf` and
`TestTerminalTabCompletion/endpoint` failed with `got="log"` instead of `"logs "`.

Action: when a requested spelling carries more than a rename, treat it as a *form* rather than an
alias entry, the same way the dotted `ctl.<action>` spelling is handled. Resolve it before alias and
scope resolution, rewrite the tail into the canonical grammar (`logf -n 7` becomes `logs -f -n 7`),
and let the canonical parser stay the only grammar. Keep it out of `commandAliases` and out of the
completion list, and document it inside the canonical command's help body so it stays discoverable.
Then check the completion list explicitly, because an alias entry is not only a dispatch decision.

Why this prevents recurrence: an alias entry looks like the obvious, minimal change, and it does
resolve the word, so a dispatch-only test passes. The two failures are both invisible from that test:
the dropped flag degrades the command into a different capability, and the extra alias silently
changes a shared completion list. Both are consequences of the registry being used for something it
does not model, so the fix is to stop using it rather than to patch each symptom.

## A green test proves nothing until it has been seen to fail

Trigger: the admission rule "an unverified session must reject send and stop but allow resume" was
implemented and covered by a new test. The test passed on the first run, which looked like
confirmation. It was not: the guard it exercised had never been observed to matter, so a test that
asserted nothing would have looked identical.

Action: after writing a test for a guard, break the guard deliberately and confirm the test fails,
then restore it and confirm it passes again. The failure message must name the behaviour, not just
report a mismatch: disabling this guard produced `calls=1` and `outcome=submitted`, which proved the
command reached the provider instead of being rejected. Delete the temporary break immediately and
re-run the suite, so the broken build cannot be mistaken for the real one.

Why this prevents recurrence: a test written after the fix encodes whatever the fixed code does, so
it passes by construction. Only the broken build shows whether the test can distinguish the two
behaviours. This case was worse than a missing test, because the defect was invisible in review:
`revalidateGeneration` compares two generations, and two empty strings compare equal, so the
comparison looked like it validated the target while it silently accepted an unverified one. The
guard was the only site that rejected it, and a green test on the guard said nothing about whether
the guard was reachable or necessary.

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

## A proposed field can be a second source of truth for a fact already on the wire

Trigger: the fix for the unverified-session count was proposed as "add `UnverifiedSessions int` to
`InventoryReport`, populated by the composer". The count was already derivable from
`sessions[].state_reason`, which every report carries, so the new field would have stored the same
fact twice. Nothing in the proposal was wrong about the symptom; only the storage location was.

Action: before adding a field to a report, a request or a stored document, check whether the fact
is already derivable from data that document carries. If it is, derive it at the layer that needs
it instead of storing it. A stored counter and the list it counts can disagree, and then the
consumer has to decide which one to trust, which is a contract question nobody asked for. State
the trade-off explicitly when deriving: a per-render pass over rows the table already iterates is
not the same cost as a per-request scan of a large document.

Why this prevents recurrence: a redundant field looks like a convenience, and it is convenient
right up to the first disagreement. Because both values are written by the same producer, the
divergence appears only after a partial update, a retry, or a second producer, and by then the
field is part of the wire contract and cannot be removed without a version bump. Deriving keeps
one source of truth and needs no protocol, storage or schema change, which is also what lets a
second adapter land without touching the Server.

## A line-range edit can delete a neighbour when the range is guessed

Trigger: while adding one paragraph to `docs/agent-cluster-protocol.md`, a line-range
replacement deleted the whole `Use stable opaque cluster resource IDs ...` paragraph and
left two blank lines in its place. The same edit also duplicated a sentence that already
existed above it. The file looked plausible, because a document with a missing paragraph
and an extra blank line still renders, and the loss was visible only in `git diff`.

Action: after any line-range edit, read `git diff` for that file before doing anything else,
and check the deletion count. A documentation edit that only adds prose must show zero
deletions; any deletion is either the intended one or a lost neighbour. When the target
region is not a single unambiguous block, replace the whole file or do a literal string
substitution on the exact text, and assert the surrounding lines before writing.

Why this prevents recurrence: a line number is a position, not an identity, so a range that
was correct when it was computed can cover a different block after any earlier edit in the
same turn. The tool reports success either way, and the damage is silent because prose has
no compiler. Comparing the deletion count against the intent is what turns "the edit
succeeded" into "the edit changed only what I meant".

## A fabricated test state and a real state can share a name

Trigger: the colour mapping for `idle`, `unknown` and `unverified` was changed to dim, and
`unknown-state` was changed with it because the name contains `unknown`. That fixture is not
the real `unknown` state: it is a made-up value that exists only to exercise the `default`
branch of `stateStyle`, so it must stay yellow. Two tests failed, and the failure looked like
a broken mapping rather than a broken fixture.

Action: before changing a value that appears in a test, check whether the test asserts the
real state or the fallback branch. A fixture whose name merely resembles a real state is
testing the default path, and changing it silently removes the only coverage of that path.
Keep a separate case for the real state, and name the fixture so the distinction is visible,
for example `unknown-state` for the fallback and `unknown` for the real one.

Why this prevents recurrence: a fixture name is chosen for readability, not for identity, so
a substring match on a real state name is not evidence that the fixture represents it. The
test still passes after the change, because the fallback branch accepts any unrecognized
value, so the loss of coverage is invisible. Asserting both the real state and the fallback
in the same table is what keeps the two paths from collapsing into one.

## A container endpoint keeps its own allowlist, so a host edit does not reach it

Trigger: the shipped `command.exec` allowlist was extended and the host conffile
`/opt/agent-cluster/conf/command-allowlist.conf` was updated and reloaded. The two container
endpoints (`ai-dev`, `topsailai-dev`) run the same binary from the same path, but their
`/opt/agent-cluster/conf` is inside the container image, not a bind mount of the host tree, so
the host file never reached them. Their own log showed `reloaded command allowlist entries=10`
at the moment the host reloaded 35, which is the only evidence that distinguishes "the file is
correct" from "the process is using it".

Action: after changing any Endpoint conffile, verify each running Endpoint separately by reading
its own reload log line and its own file content, not the host file. A container endpoint needs
the file copied into the container and its own `SIGHUP`; a host `SIGHUP` reaches only host
processes. Confirm the effective entry count per process, because the reload log prints the count
the process actually parsed.

Why this prevents recurrence: all three endpoints share one binary path and one configuration
path, so they look like one deployment. The difference is only visible in the mount table and in
each process's own log, and a host-only reload leaves the container endpoints silently on the old
policy while every host-side check passes. The failure is fail-closed for a newly added command,
so the operator sees `policy_denied` for a command the documentation says is allowed, and the
documentation looks wrong instead of the deployment.

## A shorthand that supplies a flag needs a rendered-output test, not a rewrite test

Trigger: `lf` was added as the shorthand of `list --full`. The first test set proved the tail was
rewritten into `--full <tail>` and that `tableOptionsFor` ORed the flag into the boundary value, and
both passed. Neither proved the REPL actually rendered a long value in full: the rewrite could have
been correct while `interactiveList` dropped the flag, and the OR could have been correct while no
caller passed `true`. The composed path was the only place the two halves met, and it was untested.

Action: when a shorthand carries a flag, add one test that drives the real entry point and asserts
the rendered bytes, using a fixture value that exceeds the column cap so the two layouts are
distinguishable. Pair it with a test of the plain command on the same fixture, asserting the clipped
form appears and the complete value does not, because a fixture that cannot express the failure mode
is not coverage. Then break each site in the chain in turn and confirm which tests fail: breaking the
tail rewrite failed only the interactive checks, which proved the two surfaces resolve the shorthand
at separate sites and neither test covers for the other.

Why this prevents recurrence: a rewrite test and an option test are both unit tests of one link, and
a chain of correct links can still have no consumer. The rendered bytes are the only evidence that
the flag reached the renderer. The paired clipped-render test is what stops the full-render test from
passing for an unrelated reason, such as a fixture whose value was already short enough to fit.

## A substring assertion can match inside an unrelated word

Trigger: a test asserted that the overview help does not advertise `lf`, using
`strings.Contains(overview, "lf")`. It failed, because the overview contains the phrase "on the
operator's behalf", and "be**lf**" contains the substring. The command was correctly absent; the
assertion was wrong.

Action: when asserting that a short token is absent from prose, compare whole tokens rather than
substrings. Split the text on whitespace and punctuation, or match with a word boundary, so a
two-letter name cannot be satisfied by the middle of an ordinary word. The same rule applies to
asserting presence: a substring hit is not evidence that the token is there as a token.

Why this prevents recurrence: short command names are exactly the ones most likely to appear inside
other words, and the failure direction is silent in both ways. A false positive makes a correct
implementation look broken, and a false negative would let an unwanted advertisement pass. This is
the same class of error as matching a fixture name against a real state name: a substring match is
not an identity match.

## Reading the implementation first makes the implementation the design

Trigger: asked to design a session model-selection command, the first design was written by reading
the provider's registry file, its selection function and its numbered text output, and then copying
that shape into the cluster. The result named provider files, inherited a provider numbering scheme
as if it were an identity, and would have needed a provider change to produce a structured menu. The
human rejected the direction: the cluster is the abstraction layer, so its behaviour pattern must be
defined first and the adapter must follow it.

Action: when the task is to add a capability to an abstraction layer, write the abstract resource,
the operation, the payload, the result document, the safety class, the permission and the error codes
before opening any provider source. Only then read the provider, and only to answer "what must the
adapter supply to satisfy this contract". If a sentence in the design cannot be written without
naming a provider, the design is not finished. Keep provider detail in one clearly labelled adapter
section, and check that no provider name leaked into the protocol, a Server route, a stored document
or a CLI help body.

Why this prevents recurrence: reading the implementation first feels like diligence, and it produces
a design that is guaranteed to fit the one provider that was read. That is exactly the failure: the
design is then a description of the provider rather than a contract, so a second provider cannot be
added without changing the protocol, the Server, the schema and the CLI. The abstraction layer exists
to prevent that, and the only moment it can be protected is before the provider is read. A design
reviewed against the provider will always look correct, because the provider is what it was copied
from.

## A capability gap must be checked against the provider's actual surface, not its documentation

Trigger: while listing what was missing for the session model command, the plan stated that no
machine-readable model list existed, so the numbered menu would have to be parsed from provider prose.
That was wrong. `topsailai models list --json` exists and returns a structured JSON array
(`cli/cli_topsailai/models_cli.py:287-296`, flag registered at `models_cli.py:484-489`). The human
corrected it with "你再看 topsailai models list 这个命令是支持json输出的". The claim had been carried
forward from an earlier turn and never re-verified, and it shaped the design: it was the reason a
provider change looked necessary.

Action: before recording a capability gap, run the provider command or read the subparser registration
that proves the gap. A gap claim is a factual claim about another project's surface, so it needs the
same evidence as a defect claim: the exact file and line, or the observed output. Search the subparser
registration (`add_parser`, `add_argument`) rather than the handler name, because a flag can be
registered on the parser while the handler reads it through `getattr(args, "json", False)`, and a
handler-only search shows the read without proving the flag is reachable.

Why this prevents recurrence: a gap claim is never reviewed as a claim, it is reviewed as a premise.
Every later decision inherits it, so a wrong gap does not produce one wrong sentence, it produces a
wrong design: here it made a provider change look mandatory and made the menu look inherently fragile.
The correction also split one gap into two different ones, which is the useful outcome: the structured
list exists, but it reports what is configured, while the current model is runtime state reported only
as text (`workspace/plugin_instruction/agent.py:289`). A single "no JSON" claim hid that distinction
and would have produced a catalog that silently omitted which profile is in use.

## A failing test is not another agent's until the diff names your own change

Trigger: `make test-unit-cli` failed on `TestUnitCBatch2PrefetchedHelpQuit`, and the failure was
reported to the human as another agent's concurrent edit to `internal/tui`. That was wrong. The
failure diff showed `want` containing `messages [session]` while the output contained
`messages [--max-chars N] [session]`, which is exactly the syntax this task had just added to
`help.go`. The file was not foreign at all; the expectation inside it was stale because of this
change. The mis-attribution was reported twice before the diff was read.

Action: before attributing a failure to another agent, read the failure diff and check whether the
differing text is produced by a line this task changed. The correct test is not "is the failing file
in my change set" but "does the difference come from my change". A test file that embeds generated
output will fail because of a change in a different file, so the failing file being untouched proves
nothing. Only after the diff shows a value this task did not produce is a concurrent edit the
explanation.

Why this prevents recurrence: a stale expectation in a test file looks exactly like a foreign edit,
because the file is not in the change set and the failure appears while verifying unrelated work. The
convenient explanation is also the one that requires no work, so it is easy to accept without
evidence. Reading the diff converts the question into a fact, and in this case the fact was that the
defect was self-inflicted and blocking.

## Generated help text is pinned in more than one place

Trigger: changing one `messages` syntax string in `help.go` broke two separate tests. The first was a
literal copy of the main help block in `unit_c_batch2_queue_test.go`. The second was a SHA256 digest
and byte size of the full help output in `unit_c_start_parse_test.go`, which no grep for the old
syntax could find, because a digest contains no readable text.

Action: after changing any help or usage string, search for the old text and also search for digest
pins (`sha256`, `Sum256`, `digest`) in the same package. A digest pin cannot be found by searching for
the text it covers, so it must be looked for by mechanism. When updating a digest, first confirm the
source file contains only the intended change, so the new digest can only be caused by that change;
then copy the actual value from the failure output instead of computing it separately. Check the size
field too: an unchanged size with a changed digest is evidence that the edit was length-preserving,
which is a useful confirmation that the padding was right.

Why this prevents recurrence: a literal expectation fails loudly and points at the line, while a
digest fails with two opaque hex strings and no indication of which text changed. The digest is
therefore the harder half of the same edit, and it is invisible to a text search. Confirming the
source diff before accepting a new digest is what keeps the pin meaningful rather than merely
updated to whatever the code now produces.

## Byte parity with a provider is not a quality criterion

Trigger: the `messages` renderer was rewritten to reproduce the provider's own human-readable
output byte for byte, and that was reported as the acceptance criterion. The human rejected the
result: a message body that the provider stores as a JSON object still printed as braces and
quotes, because the provider's own non-JSON surface dumps raw JSON in that case. Copying the
provider faithfully reproduced its defect.

Action: when the requirement is "make this readable", the criterion is readability, not equality
with the source. Read the provider's output to learn the layout, then ask what the provider does
with each *shape* of data, and improve the shapes it handles badly. State the criterion in terms
of what the operator sees, and keep byte parity only for the cases where the provider is already
correct, such as plain prose.

Why this prevents recurrence: byte parity is measurable, so it feels like a rigorous criterion,
and a `cmp` that reports no difference looks like proof of success. It is proof of sameness, not
of quality, and it silently converts "the provider is wrong here" into "we are wrong here too".
The abstraction layer exists precisely to be better than any single provider, so a criterion that
forbids improving on the provider contradicts the layer's purpose. The tell is a requirement
phrased as "copy it exactly" applied to a case where the source output is visibly unreadable.

## A renderer that recognises shape must not name the provider's fields

Trigger: the fix for the unreadable body could have been written as "if the body has `raw_text`
and `step_name`, print the text". That would have worked for this provider and broken the
abstraction: the renderer would then encode one provider's record format, and a second provider
would need a renderer change.

Action: split the responsibility by layer. The adapter owns the provider's record shape and
unwraps it, because that shape is provider detail. The renderer owns only generic JSON shapes:
object, array, scalar, nested, empty. A renderer that needs a field name to decide what to print
is doing the adapter's job in the wrong place.

Why this prevents recurrence: the provider-specific version is shorter and passes every test on
the only provider that exists, so review cannot see the defect. It appears later as a renderer
that must be edited for every new adapter, which is exactly the coupling the cluster contract
forbids. The generic version is testable with fixtures that name no provider at all, and those
fixtures keep working when the provider's record format changes.

## A help body and a help syntax line are two different sources

Trigger: `--brief` was added to `list` and documented in the catalog entry, and the interactive
`help list` body showed it. The standalone `help list` Syntax line still read
`list [--clean] [--full]`, because `PrintNonInteractiveCommandHelp` overrides `entry.syntax` with a
hardcoded string per command (`internal/tui/help.go:326`). The catalog entry was correct, the
parameters and examples were correct, and only the one-line syntax override was stale. Every test
passed, because the tests asserted the parameters and the examples, never the Syntax line.

Action: when adding a flag to a command that exists on both surfaces, grep for the command's syntax
string, not only for the flag name. A per-surface override is a second source of truth for the same
grammar, so it must be edited separately and asserted separately. Assert the exact Syntax line on
each surface, because a `Contains` check on the flag name passes as soon as the parameter list
mentions it, even while the syntax line contradicts it.

Why this prevents recurrence: the override exists precisely so the standalone surface can state a
different grammar, so it is legitimate code rather than a duplicate to be removed. That also means it
will never be caught by a test that checks the shared catalog, and the disagreement is invisible in
review because both strings are plausible. Reading the rendered help output of the real binary is what
turned "the flag is documented" into "the flag is advertised where the operator looks".
## A line number from a sed window is relative to the window, not the file

Trigger: while fixing a stale golden in `unit_c_batch3_state_test.go`, the line number was
taken from a `sed -n '66,80p'` window and used directly in a line-range overwrite. It
replaced the `if` line instead of the `want` line, leaving two `want` lines and an orphaned
`Fatalf`. The same class of accident recurred throughout this task: an insert placed a
capability entry outside its slice, an overwrite duplicated a doc comment, an overwrite
deleted a `name :=` assignment, an insert split a `case` body so its label was lost, and an
insert placed an `entry.examples` line inside the next `case` block.

Action: obtain every line number with `grep -n` against the whole file, never by counting
inside a `sed` window. Before overwriting, print the exact region and confirm the first and
last line are the ones intended. When the region is a `case` block, include the `case` label
and the closing brace in the replaced range, because an insert immediately after a label
splits that case's body. When a small file needs several interdependent edits, rewrite the
whole file instead of chaining line-range edits.

Why this prevents recurrence: a line number is a position, not an identity, and a window
offset is a third coordinate system that looks like the second. The tool reports success
either way, and Go only catches the damage when it happens to produce invalid syntax; a
duplicated comment, a lost assignment or a misplaced examples line compiles fine and is
invisible in review.

## A stale golden can predate your change, and a worktree at HEAD is the only proof

Trigger: `unit_c_batch2_driver_test.go` failed while verifying the model command. The failure
looked like a consequence of the new help entry. It was not: `git log -S 'after a completed
start' -- ./internal/tui/help.go` showed commit `8e92ee7e` added two start-tail notes to
`help.go` without updating that golden, and a detached worktree at HEAD `1523008b` reproduced
the failure before any of this task's changes existed.

Action: when a golden-value test fails after a deliberate surface change, do not assume the
delta is yours. Run the same test in a detached worktree at HEAD. If it already fails, the
golden was stale before the change: fix it in the same commit, but label it pre-existing in
the commit body so it is not mistaken for scope creep. If it passes at HEAD, the delta is
yours and the golden is telling you something about your change.

Why this prevents recurrence: a surface-inventory golden encodes the whole command list, so
any legitimate addition breaks several of them at once and the noise hides which failure is
new. Without the HEAD comparison, a pre-existing defect gets silently absorbed into an
unrelated commit, and the next person cannot tell which change was responsible. The worktree
is the only evidence that separates "my change broke this" from "this was already broken".

## A styled prefix is invisible to an assertion that matches plain text

Trigger: the follow status lines gained a `log.follow>` prefix rendered bold green through
`RenderNamedPrompt`. The unit tests passed, because they compared the rendered string against an
expected string that contained the escape sequences. The BDD scenarios failed, because they assert
with `strings.Contains(output, "log.follow> res_")` and the real output is
`\x1b[1;32mlog.follow>\x1b[0m res_`. The message was correct and the assertion could not see it.

Action: when a rendered line gains styling, check every assertion that matches it as text. A unit
test that compares whole rendered strings is safe, because the expected value carries the same
sequences. A substring assertion is not: it silently requires the plain form. Either strip the
styling before asserting, or assert on a structural property. Here `tests/bdd/steps_follow.go` gained
`stripFollowSGR`, which removes the four sequences the prefix and the severity styles use.

Why this prevents recurrence: the failure direction is the dangerous one. A styled prefix makes a
correct message look absent, so the natural conclusion is "the prefix was not applied" and the fix
would be to remove the styling that was just requested. The real cause is that the assertion was
written against the unstyled form, and nothing in the test names that assumption. The same trap
applies to any surface that is asserted as text but rendered with colour: a PTY-driven BDD scenario
with a real `TERM` sees sequences that an in-process unit test with colour disabled never produces,
so the two layers disagree about what the output is.

## A child process that inherits the environment inherits every credential the parent holds

Trigger: while adding `watch --trigger`, the script was about to be started with the parent's
environment. The client process carries `AGENT_CLUSTER_ENDPOINT_TOKENS`
(`src/main/agent-cluster-cli/endpoint_tokens.go:15`), one variable holding the token of every
Endpoint in the fleet, plus `AGENT_CLUSTER_SERVER_TOKEN` and `AGENT_CLUSTER_AUTH_SCOPES`. A
notification script that only wanted to post a message would have received cluster-wide authority
it never asked for, and nothing in the script or its review would have shown that.

Action: when a process starts a child that is not part of the same trust domain, build the child
environment from a whitelist instead of inheriting it. Name the variables the child is documented
to receive, add the few runtime basics it needs (`PATH`, `HOME`, locale, `TMPDIR`), and set
`TERM=dumb` so a script cannot emit terminal control sequences into a surface that is not a
terminal. A blacklist is not a substitute: it silently stops protecting the moment a new credential
variable is added, and the addition looks unrelated to the script.

Why this prevents recurrence: inheritance is the default and it is invisible. `exec.Command` with a
nil `Env` looks like the simplest correct code, and it is correct for a child in the same trust
domain, which is why the pattern is copied from ordinary subprocess code without a second thought.
The leak is also one-directional and silent: the script works, the notification arrives, and the
only defect is an authority the script should not have had. A test that asserts the credential
variables are absent from the child environment is the only evidence that the whitelist is real,
because the working script proves nothing about what it was handed.

## A trigger that fires on a state fires again on every tick

Trigger: the first shape of the `watch --trigger` detection was "fire when the state is
`waiting_input`". Three failures follow from that shape and all three are user-visible: starting the
loop fires once for every session that was already waiting, a session that stays waiting fires on
every tick, and a script that fails is retried on the next tick forever. The fix was a baseline map
keyed by the same identity the row table uses, so only a real transition fires.

Action: when a mechanism reacts to a condition that is sampled rather than delivered, detect the
edge and not the level. Record a baseline on the first observation and fire nothing, because the
first observation is not a transition. Reset the baseline without firing when the identity's
generation changes, because a replaced process is a new subject rather than a transition of the old
one. Delete baselines for identities that are no longer reported, so the map cannot grow without
bound. Write the rule as one predicate over `(previous, next)` so a future transition is one added
clause rather than a second detection path.

Why this prevents recurrence: a level check is shorter, reads correctly, and passes any test that
only asserts "the script ran". The three failures are all about *when* it ran, so a test that counts
invocations is the only thing that distinguishes the two designs. The baseline also has to be keyed
by a stable identity rather than a row number, because a row number is a position that is rebound on
every render, and a rebound key looks exactly like a transition.

## A byte-order assertion cannot see a cursor column

Trigger: the guided-answer echo was written by the editor at submit time, and the test asserted that
`(ai-dev)` appears after `1` in the captured output. It passed. The echo was still wrong: the cursor
was moved to column 1, so on a one-row block the echo overwrote `start.endpoint> ` instead of
following the answer. The rows the editor renders hold text only, and the prompt is written beside
row zero, so a width taken from the text alone omits the prompt.

Action: when output is placed by a cursor movement rather than by stream order, assert the movement
itself. Capture the escape sequence and compare it exactly, for example `"\r\x1b[17C (ai-dev)"`, and
compute the expected column from the prompt width plus the answer width. A `strings.Index` comparison
proves only that two substrings appear in order, which stays true while the cursor is anywhere.

Why this prevents recurrence: a terminal is a grid, not a stream, so the same bytes render differently
depending on where the cursor was. The failure is invisible in the captured text because the text is
correct; only the position is wrong. This is the same class as the recorded lesson about a styled
prefix being invisible to a plain-text assertion: the assertion and the defect live in different
dimensions, so a green test certifies nothing about the dimension that broke.

## A fallback branch must repeat the guard its seam branch already has

Trigger: `readPromptLineWithEcho` had two branches. The seam branch passed the echo to the reader,
which guards it internally. The fallback branch called `echo(line)` directly and checked only
`err == nil && !overflow && line != ""`. The pre-existing `TestPromptReaderGating` panicked with a nil
dereference, because that test supplies a reader and no echo.

Action: when a function has a seam branch and a fallback branch that do the same job, list the guards
each branch needs and confirm both have them. A guard that lives inside the seam implementation is not
inherited by the fallback, so it must be repeated at the call site. Prefer one shared helper that both
branches call, so the guard cannot exist in only one of them.

Why this prevents recurrence: the seam branch is the one that gets exercised while the feature is
being built, because the editor is the interesting case. The fallback is the piped or `TERM=dumb` path,
which is exactly the path a developer's own terminal never takes. The nil dereference therefore
appears only in a test that was written for a different purpose, and only because that test happened
to inject a reader without an echo.

## A newer committed revision must acknowledge an older pending publication

Trigger: while reviewing `inventory_ack`, the first storage check acknowledged an idempotent retry only
when the committed JSON exactly matched the submitted report. If Server had already committed revision
8 while Endpoint retried revision 7 after losing its ACK, revision 7 was correctly not written but was
also never acknowledged, so Endpoint would retry an obsolete report forever.

Action: define acknowledgement against the latest-value contract rather than byte equality alone. An
exact same-revision document is represented, a higher committed revision supersedes an older submitted
revision, and a same-revision document with different content is a conflict that must not be
acknowledged. Test all three cases together because each comparison protects a different boundary.

Why this prevents recurrence: latest-only storage deliberately discards older states, so requiring the
old bytes to remain stored contradicts its retention model. At the same time, revision equality alone
cannot prove content identity. Combining revision ordering with content equality at the equal-revision
boundary lets retries converge without hiding conflicting immutable reports.

## A global CLI flag shown after the command is not necessarily parsed as a flag

Trigger: the first standalone cleanup examples used `clean endpoint-1 res_abc --yes`. This project uses Go's standard `flag` parser, which stops parsing options at the first positional command, so `--yes` remained in the command arguments and the existing misplaced-flag guard rejected the documented example. The implementation was correct, but the new help and command-surface documentation advertised an invocation that could not run.

Action: when documenting a standalone command that uses process-global options, inspect the parser boundary and place those options before the command, as in `agent-cluster-cli --yes clean endpoint-1 res_abc`. Add a help-surface test that checks both the command syntax and the required option rather than validating the command name alone.

Why this prevents recurrence: an option's visual proximity to a command does not prove that the parser for that command receives it. The help can look conventional while every copied invocation fails before dispatch. Checking the actual parser boundary keeps examples executable and prevents documentation from defining a second, unsupported grammar.

## A whitelisted child environment removes the variables a desktop notification needs

Trigger: the watch trigger script was extended to raise an on-screen popup. A plain `notify-send`
inside the script failed with `Cannot autolaunch D-Bus without X11 $DISPLAY`, because
`triggerEnvironment` (`internal/tui/trigger.go:169-199`) forwards only `PATH HOME LANG LC_ALL TZ
TMPDIR` plus `TERM=dumb`. The script had already solved the same problem for audio by discovering
`/tmp/pulse-*/native`, but the session bus is a second, independent discovery problem.

Action: when a script runs under a whitelisted environment, treat every desktop service it needs as
something to discover rather than something to inherit. For D-Bus, check `/run/user/<uid>/bus` and
also read `DBUS_SESSION_BUS_ADDRESS` from the processes of the desktop account, because a session
started by a display manager publishes an abstract socket such as `unix:abstract=/tmp/dbus-XXXXXXXX`
and `/run/user/<uid>/bus` does not exist on such a host. Then send as the account that owns the
session: a session bus refuses another account's connection and reports it as `The connection is
closed`, which reads like a transport failure rather than a permission failure.

Why this prevents recurrence: the whitelist is a security property and must not be widened, so the
missing variable can never be fixed by forwarding it. The failure is also silent in the way that
matters: the script still exits 0 by design, so a broken popup and a working popup are
indistinguishable from the exit status. Only capturing the `org.freedesktop.Notifications.Notify`
call on the bus, or seeing the popup, proves the channel works. This is the same class as the
recorded lesson about a styled prefix being invisible to a plain-text assertion: the evidence and the
behaviour live in different places, so a green result certifies nothing.

## Retention failure must stop the append it was meant to bound

Trigger: input-history rotation reported deletion or rename errors and then continued appending. A failed cleanup could therefore leave the active file above its configured bound or overwrite a retained backup, while a successful expired-backup deletion was silent.

Action: make retention maintenance return an error to the append path and abort the append when any stat, deletion or rename fails. Log every successful backup deletion with the exact path, and test both the successful deletion event and the failure boundary, including unchanged active content and unchanged persistent recall.

Why this prevents recurrence: retention is part of the write contract, not optional housekeeping. Continuing after it fails makes a bounded append-only file unbounded while still reporting the input as recorded. Failing the append preserves the last known retained state, and an explicit deletion event makes irreversible cleanup observable.
