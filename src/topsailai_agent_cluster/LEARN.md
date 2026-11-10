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
