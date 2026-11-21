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

That defect was resolved by removal, not by adding the missing forwarding step. `0391ba56` deleted the
Endpoint-side catalog in full, including the `--control-action-file` flag, the
`AGENT_CLUSTER_ENDPOINT_CONTROL_ACTION_FILE` read, the capability intersection and the SIGHUP reload, and
`2b58a0a2` deleted `internal/controlaction`. The key is no longer read by any component, so its absence
from `scripts/agent-clusterctl` is correct and adding an `args+=` line for it would forward a value
nothing consumes. The `ctl.` family now comes from the `ADAPTERS` capability entries an operator
declares, and the catalog is Provider-side configuration read through
`AGENT_CLUSTER_TOPSAILAI_CONTROL_ACTIONS`.

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

## A persisted online state is stale after the process that owned the connection restarts

Trigger: while adding Server-side expiry for offline Endpoint inventory, the first design selected only
rows already marked `offline`. After an unclean Server stop, a persisted Endpoint row can still say
`online` even though no channel survives the Server process. That abandoned identity would therefore
never become eligible for expiry and its old inventory would remain indefinitely.

Action: at the final pre-serve startup checkpoint, mark every persisted `online` Endpoint offline without
refreshing its `update_at_ms`. A real reconnect publishes a newer online observation normally. Keep this
recovery after configuration and service validation, so a Server that fails before it is ready does not
mutate connection state merely because an operator attempted to start it.

Why this prevents recurrence: connection state describes a relationship with one running Server process,
not durable truth. Persisting it supports restart diagnostics, but replaying `online` as current state
confuses historical evidence with a live channel. Preserving the old timestamp also matters: refreshing it
at startup would grant every abandoned identity a new retention window on every restart and could keep
stale inventory alive forever on a frequently restarted Server.

## A component-prefix migration needs a symmetric compatibility inventory

Trigger: the Server, Endpoint and CLI environment names were migrated in separate logical units. The
Endpoint and CLI sections of `docs/Environment_Variables.md` gained explicit deprecated-to-primary
mapping tables, but the Server section did not. Every Server alias worked and all tests passed, so the
omission was visible only when the three component contracts were compared side by side during the
final review.

Action: for a cross-component naming migration, maintain one owner-by-owner inventory containing the
primary name, deprecated name, reader, deployment emitter, documentation row and compatibility test.
Review the inventory horizontally as well as reviewing each component vertically. When generating
per-file Git review evidence from a project below the repository root, address files from the Git top
level and require every expected diff file to be nonempty; a successful command that produces an
empty diff is not review evidence.

Why this prevents recurrence: independent component commits can each be internally correct while the
public migration contract is asymmetric. Tests prove that aliases work, but they do not prove that an
operator can discover every alias. A single compatibility inventory makes a missing component row
visible, and a nonempty-diff assertion prevents a path-base mistake from silently certifying files
that were never reviewed.

## A credential rename must update every negative leak assertion

Trigger: after the CLI Server credential was renamed to `AGENT_CLUSTER_CLI_SERVER_TOKEN`, the trigger
child-environment security test still populated and rejected `AGENT_CLUSTER_SERVER_TOKEN`, a name the
CLI does not use. The production whitelist remained safe, but the test no longer proved that the
formal Server credential, its transitional alias or its legacy alias could not reach a notification
script.

Action: whenever a credential name changes, search both positive consumers and negative assertions
that enumerate forbidden environment keys. Update the security test with the formal name and every
accepted compatibility alias, then run the whole owning component's test target rather than only the
single test.

Why this prevents recurrence: a whitelist implementation can stay correct while a stale test gives
false confidence about the wrong variable. Testing every accepted spelling keeps the non-leakage
contract aligned with the compatibility contract, so a future change from a whitelist to inherited
environment would expose every supported credential path.

## Removing an implementation seam requires deleting its test callers too

Trigger: the Endpoint Provider CLI replacement plan required deleting the old `CommandAdapter`, but the
first removal scope named only production factories and protocol code. The test harness, integration
launchers, BDD world, manual-test scripts, configuration tests and Makefile package groups still created
or imported the old Adapter, so deleting production code alone would have broken verification or kept a
second executable seam alive under `tests/`.

Action: before deleting an implementation boundary, inventory every constructor, import, protocol flag,
fixture executable, launcher and package-list reference across production and test code. Migrate tests
that assert still-valid public behavior to the replacement seam, and delete tests that assert only the
removed implementation. Make absence from executable test infrastructure part of the same structural
gate as absence from production code.

Why this prevents recurrence: test infrastructure is an active caller, not a historical document. If it
keeps the removed protocol alive, the project either cannot compile after deletion or must retain a
hidden compatibility implementation solely for tests, contradicting the single-seam architecture. A
complete caller inventory makes production replacement and verification migrate as one logical unit.

## A blocking callback inside a batch cleanup delays every later resource release

Trigger: the first stale-peer sweep processed each expired Endpoint as `close connection -> run
OnDisconnect` before moving to the next Endpoint. `OnDisconnect` writes the offline transition to
SQLite synchronously, so one blocked database write could leave every later expired WebSocket open
even though all of those peers had already been removed from the authoritative map.

Action: separate batch cleanup into phases according to urgency and blocking risk. First detach and
close every expired connection, then fail pending work and run persistence callbacks. Keep all of
those operations outside the shared channel lock, and retain the exact peer identity so a late read
loop cannot affect a replacement connection.

Why this prevents recurrence: removing a peer from the routing map stops new requests, but it does
not release the socket or its read loop. Interleaving resource release with a fallible synchronous
callback lets one Endpoint's storage latency retain unrelated Endpoint resources. Closing the whole
batch first makes connection cleanup independent across Endpoints while preserving durable offline
publication afterward.

## Extracting a shared submission path must not create a second command budget

Trigger: removing the interactive `btw` confirmation meant the direct form and the confirmed form
had to share one submission body. The body was extracted from `interactiveConfirmedAction` into
`submitInteractiveAction`, and the first version of the helper created its own `commandContext(parent)`
internally. That silently doubled the command deadline for every operation that still confirms —
`stop`, `interrupt`, `ctl`, `drive start`, `drive stop`, `clean`, `resume` and model selection — because
the caller had already created a budget to revalidate the target and the helper then created another.

Action: when extracting a helper out of a function that already owns a context, pass the caller's
context in and let the helper use it, instead of letting the helper derive a new one. Only the caller
that has no budget yet should create one. Here the direct form creates its own `submitCtx` exactly as
the explicit `send` path does, while the confirmed form passes the context that already revalidated the
target, so a confirmation never buys a second deadline. Keep `parent` as a separate parameter when a
post-submit step needs its own bounded budget, and say so in the helper's doc comment.

Why this prevents recurrence: a helper that creates its own context looks more self-contained and
reads as the safer extraction, and every test still passes because a doubled deadline only changes
timing, never behaviour. The defect is invisible in the diff: the added line is correct in isolation
and the removed line was the only evidence of the original budget. Writing the budget ownership into
the doc comment is what makes the next extraction check it rather than rediscover it.

## Adding an identity dimension requires every consumer and test double to enforce it

Trigger: the resource mapping key changed from `(adapter_id, provider_key)` to
`(adapter_id, resource_kind, provider_resource_key)`. The storage migration and production mapper
were correct, but the Collector initially reused a mapping after checking only `adapter_id`, and a
TopsailAI test mapper generated IDs without `resource_kind`. A Task mapping could therefore be
accepted as a Session mapping in one production path, while tests could still collapse two distinct
resource kinds onto one synthetic ID.

Action: when an identity gains a dimension, enumerate every writer, lookup consumer, cache key and
test double, then require each one to carry and validate the complete identity. Add a negative test at
each boundary that supplies the right old dimensions and the wrong new dimension. Search for the old
field and method signature after migration so an omitted call site cannot survive as an implicit
default.

Why this prevents recurrence: changing a database primary key protects only database lookups. A
consumer that validates a subset can erase the new distinction after lookup, and a test double that
omits it can certify collisions the real store prevents. Enforcing the full tuple at every boundary
makes the schema rule an application invariant instead of a storage-only convention.

## Every process-group termination branch must wait for cleanup

Trigger: the Provider conformance runner correctly killed and waited for its process group on timeout
and cancellation, but the stdout-overflow branch only sent the group kill before returning. A Provider
helper could therefore outlive an invocation specifically when excessive output triggered the safety
limit, even though the same runner proved cleanup on its main timeout path.

Action: centralize or audit every branch that terminates an owned process group, including timeout,
cancellation, output-limit rejection and post-exit helper detection. After sending the exact group
signal, wait until that same group is observably gone before returning, and test cleanup with a helper
whose PID is reported before termination.

Why this prevents recurrence: process cleanup is a property of every exit path, not of the common one.
A safety branch is often reviewed only for its error classification, so a correct kill call looks
complete while asynchronous descendants still exist. Waiting on the owned group turns a requested
termination into verified resource release and keeps one malformed Provider from leaking processes.

## A failed SQLite commit can leave the pooled connection inside its transaction

Trigger: Endpoint expiry reached `COMMIT` while another SQLite connection held a read lock. SQLite returned `SQLITE_BUSY` and kept the underlying transaction active, but `database/sql.Tx.Commit` had already marked the Go transaction finished, so the deferred `Rollback` could not clean it. The Server had one pooled connection, and every later inventory write failed with `cannot start a transaction within a transaction`.

Action: when the driver can leave a transaction active after commit failure, pin one `sql.Conn`, issue `BEGIN` and `COMMIT` on that connection, and issue `ROLLBACK` on the same connection with an independent cleanup context before returning it to the pool. If rollback cannot be confirmed, mark the driver connection bad so the pool discards it. Put connection-local PRAGMAs in the driver DSN so a replacement connection receives the same durability and lock-wait settings. Test with a real second SQLite connection that holds a read transaction until commit fails, then release it and prove the next write succeeds.

Why this prevents recurrence: a deferred rollback only works while its transaction handle still owns a usable driver transaction, and a one-connection pool turns one poisoned connection into a permanent write outage. Same-connection cleanup removes the active transaction before reuse, discarding handles the unprovable case, and per-connection configuration prevents recovery from silently changing database behaviour.

## An idle terminal poll must be byte-silent without losing resize reflow

Trigger: interactive `watch` and an idle `logf` produced about 5 KB/s of SSH traffic even when no table changed and no log record arrived. The 50 ms input poll correctly found no pending payload, but its idle callback still erased and redrew the prompt unconditionally. A few dozen terminal bytes per poll became persistent encrypted SSH packets and acknowledgements, so application-level output that looked negligible became hundreds of megabytes per day on a remote connection.

Action: make the pending-output function report whether it actually wrote terminal bytes, and redraw the input block only after real output. Track the width used for the last render separately, so a terminal resize still causes one necessary idle redraw and subsequent unchanged polls return to complete silence. Test byte identity between zero idle polls and several empty idle polls, then separately test that a width change adds exactly one redraw.

Why this prevents recurrence: polling frequency controls detection latency, not permission to write. Keeping the 50 ms poll preserves responsive streaming, while making an unchanged poll byte-silent removes transport amplification. Treating resize as an explicit state change avoids the tempting but incorrect one-line optimization that would suppress all idle redraws and leave wrapped prompts stale until the next keypress or output record.

## Reusing a renderer means inheriting its decoder assumptions

Trigger: `provider_response` was rendered by reusing `renderStructuredBody`, which already existed for
conversation bodies. The reuse was correct, but the function's decoder carried two assumptions that
were harmless for a message body and wrong for a provider document. `json.Unmarshal` into `any`
decodes every number as `float64`, so `1794470400000` printed as `1.7944704e+12`; and a decoder reads
one value and ignores the rest, so a JSON Lines document would have rendered only its first record and
silently dropped the others. Both were found by running the decoder on the real shapes before
committing to the reuse, not by reading the function.

Action: before reusing an existing renderer or parser for a new input, run it on the new input's real
shapes and compare the output against what the operator needs. Check the numeric representation, the
number of values the decoder consumes, and whether trailing content is detected. Here the fix was
`json.NewDecoder` with `UseNumber()` plus an EOF guard that falls back to verbatim output, so a
document that is not exactly one JSON value is never partially rendered.

Why this prevents recurrence: a shared helper is reviewed as a solved problem, so its assumptions stop
being visible the moment it is reused. The two defects are both silent in the direction that matters:
scientific notation is still the same value, and a dropped trailing record still looks like a complete
answer. Neither shows up as a changed line in the diff, because the reuse itself is the change.

## A nested fixture's indentation is one level deeper than the parent key

Trigger: while asserting that a nested list renders as bullets, the expectation used two spaces
(`"  - a"`) for a list that sits inside `response.items`. The renderer emitted four spaces, because
`items` is one level below `response`, which is itself one level below the document root. The renderer
was correct and the expectation was wrong, and the failure read like a rendering defect.

Action: when asserting indentation, count the depth from the document root to the value, not from the
nearest key that happens to be mentioned in the test name. Prefer an exact whole-line comparison so the
indentation is actually asserted, and derive the expected depth from the fixture rather than from the
sentence describing it.

Why this prevents recurrence: an indentation assertion is the only thing that proves nesting, so
loosening it to a substring match would make the test pass while losing the property it exists to
check. The failure is also easy to misattribute, because the message names the renderer's output rather
than the expectation, and the renderer's output is the part that looks wrong.

## A shared wait-marker that depends on the guard under test collapses attribution

Trigger: the endpoint-expiry BDD suite seeded a `sweep-sentinel` endpoint in every scenario and waited
for it to disappear as proof that a sweep had run. The sentinel was seeded with
`offline_since_at_ms = 0`, so it only became expirable through the startup backfill. Breaking the
backfill therefore failed **all six** scenarios, including `a_connected_endpoint_is_never_expired`,
which has nothing to do with the backfill. The suite looked sensitive, but it could not attribute a
failure to a boundary.

Action: when a test needs a marker that proves a shared mechanism ran, seed that marker so it is
eligible on its own, independent of every guard the scenarios are meant to discriminate. Here the
sentinel now carries a positive `offline_since_at_ms`, so it expires regardless of the backfill, and
breaking the backfill fails only the legacy scenario. Write the reason into the seed function's
comment, because the zero value looks like the natural choice and the coupling is invisible.

Why this prevents recurrence: a shared marker is convenient precisely because it is shared, so it is
easy to give it the same shape as the scenario fixtures. That shape is what couples every scenario to
one guard. The failure mode is the opposite of a missing test: the suite is green, and it does fail
when the guard breaks, so it appears to work. Only breaking one guard at a time reveals that the
failures are not attributable. The same trap applies to any shared readiness probe, shared fixture row
or shared "wait until" condition whose eligibility depends on the code path under test.

## A guard that production writes cannot reach must be proven at the storage layer

Trigger: removing `connection_state != 'online'` from both expiry DELETEs did not fail any BDD
scenario, including the one named `a_connected_endpoint_is_never_expired`. Investigation showed the
guard is unreachable through production writes: `UpsertEndpoint` forces `offline_since_at_ms = 0` for
an online state, and `MarkPersistedEndpointsOffline` converts every online row to offline before a
sweep runs. So `offline_since_at_ms > 0` already excludes online rows, and the state guard only
protects against a corrupt or hand-edited row.

Action: when a deliberate break does not fail the test that claims to guard it, first decide whether
the guard is redundant or the test is wrong, and prove which by tracing the write paths that can
produce the guarded state. If no production path can produce it, the guard is defense-in-depth and
must be proven where the state can be created directly, which is usually the storage layer. Seed the
corrupt state there, assert the row survives, and confirm the test fails when the guard is removed.
Then narrow the BDD scenario's stated claim to the reachable invariant, and record the distinction so
nobody later reads that scenario as proof of the guard.

Why this prevents recurrence: a safety scenario that passes for the wrong reason is worse than no
scenario, because it certifies a guard nobody has exercised. The tempting response to a break that
does not fail is to assume the guard is redundant and delete it, which removes the only protection
against a corrupt row. The other tempting response is to leave the green scenario alone, which keeps
a false claim in the suite. Tracing the write paths answers the question with evidence, and moving the
proof to the layer that can create the state keeps the guard tested without pretending BDD covers it.

## A gate on the action does not guard the menu that offers the action

Trigger: `start` and `cd` printed every registered endpoint as a numbered choice, including offline
and degraded ones, while the request that followed was correctly refused. The operator was offered a
row, chose it, and was refused afterwards. Auditing all 11 `ListEndpoints` call sites showed the
asymmetry: 13 sites refused a *named* unusable endpoint before sending, but only 2 sites printed a
list and neither filtered it.

Action: treat "what may be offered" and "what may be executed" as two separate decisions with two
separate proofs. A selection list is a third kind of access beside a store read and a machine
access: it may read every record, but it must not offer a row the operator cannot use. Give the
filter one shared helper (`selectableEndpoints`) instead of letting each list invent its own rule,
and prove it by removing it and watching the list assertion fail. Then prove the resolution sites
separately, because a list assertion only proves the row was not printed, never that the identifier
could not be typed.

Why this prevents recurrence: a refusal gate makes the command safe, so the defect is invisible to
every test that asserts the refusal. The operator still wastes a choice and reads a failure that
looks like a fault. The two decisions also drift apart silently: three different state predicates
existed (`validateEndpointOnline`, `endpointOnline`, `endpointDegraded`) and most lists used none of
them. One shared helper plus one proof per decision keeps the menu and the gate from diverging.

## A numbered list and the answer that selects from it must share one filtered slice

Trigger: filtering the `start` wizard's printed list was not enough, because `start 1` resolved the
bare number against every registered endpoint. The wizard printed `1. online-b` while `start 1`
selected an offline endpoint that was never shown, so the same number meant two different machines.

Action: when a prompt prints a numbered list and later resolves a bare number, both must be computed
from the same slice, in the same order. Filter once, print that slice, and resolve against that
slice. Preserve the order, because reordering silently changes which endpoint a number means. A
named identifier is different: resolve it against every record so a machine that is not offered
reports its real state instead of being described as absent.

Why this prevents recurrence: the printed list and the resolver are two functions, so filtering one
leaves the other addressing rows the operator never saw. The failure is silent because the number is
valid, just for a different machine. Sharing the slice makes the two views structurally identical,
and the order requirement is the part that a later refactor is most likely to break.

## A provider version directory is hardcoded in the site configuration

Trigger: the Provider CLI package installs to a versioned path
`/opt/agent-cluster/providers/topsailai/<version>/agent-cluster-provider-topsailai`, and
`node.conf` names that exact path in `ADAPTERS.command`. Upgrading the Provider package alone
therefore leaves the Endpoint invoking the previous binary, because the configuration still points
at the old version directory. The binary package upgrade succeeds, the Endpoint starts normally,
and nothing in the startup log looks wrong.

Action: when upgrading a Provider CLI, rewrite `ADAPTERS.command` in every site configuration to
the new version directory before building the config packages, and verify the packaged `node.conf`
names the new path. After deployment, confirm on each node that the provider directory listing
contains only the new version and that `ADAPTERS.command` resolves to it.

Why this prevents recurrence: the version directory is a second source of truth for which binary is
active, and it lives in configuration rather than in the package. A package upgrade and a
configuration upgrade are two separate steps, and only the second one changes which executable runs.
The failure is silent because the old binary is still a valid binary: it starts, it answers, and it
reports a healthy descriptor. The only symptom is that behaviour which changed in the new version
does not appear, which is indistinguishable from a feature that was never implemented.

## A conffile prompt leaves a dependency package unconfigured

Trigger: `dpkg -i` over a non-interactive SSH session stopped at
`Configuration file '/opt/agent-cluster/conf/endpoint/node.conf' ... [default=N] ?` and then
reported `end of file on stdin at conffile prompt`. The config package stayed unconfigured, so
`agent-cluster-endpoint` failed with `dependency problems - leaving unconfigured` even though its
own files had been unpacked successfully.

Action: when installing a config package whose `node.conf` was deliberately regenerated from the
live node, pass `--force-confnew` so the packaged file wins without a prompt. Then verify with
`dpkg-query -W -f='${Package} ${Version} ${Status}'` that every package reports
`install ok installed`, not merely a version string.

Why this prevents recurrence: `dpkg-query -W` prints a version for an unpacked-but-unconfigured
package, so a version check alone looks successful while the service cannot start. The dependency
failure is reported against a different package than the one that prompted, which sends the
investigation to the wrong package. Only the `Status` field distinguishes installed from
unconfigured, and only `--force-confnew` removes the prompt that a non-interactive session cannot
answer.

## Two interfaces of one provider can use two identifier spaces

Trigger: the cluster reported a provider session identifier (`sad-*`) and passed it to
`topsailai workspace resume -s`, which resolves its target through the session database. The
authority check that ran first read `workspace list`, which does contain that row, so the check
passed and the command was issued. The command then failed with `session_not_found`, because the
session database is keyed by a different identifier form and does not contain analysis sessions at
all. Resume therefore worked for `wa-*` sessions and could never work for `sad-*` sessions.

Action: when one provider exposes two interfaces that both accept "a session identifier", confirm
that both resolve the identifier against the same store. Run the authority interface and the
executing interface with the same identifier and compare the results. If the authority interface
finds the row and the executing interface does not, the two interfaces disagree about identity and
the authority check is not a preflight for the command.

Why this prevents recurrence: the authority check looks like a complete preflight, so a passing
check reads as proof that the command can succeed. The failure is also asymmetric, because some
identifiers work and others do not, which reads as an intermittent provider fault rather than a
systematic identity mismatch. The two interfaces are usually written at different times for
different purposes, so nothing in either one names the other's store. Comparing them with one
identifier is what turns "the target was validated" into "the target is addressable".

## A resource kind that cannot support an operation must not be offered for it

Trigger: the cluster reported 12 analysis sessions as `unknown` with an empty generation and offered
them as resume candidates. Those sessions are driver sessions, absent from the session database by
design, so resume could never succeed. Every attempt produced a provider error that looked like a
fault rather than a refused capability, and the operator reported the whole command as unusable.

Action: when a resource kind cannot support an operation, exclude it where the resource is reported
or mark it unsupported there, not where the operation fails. A capability that is advertised must be
reachable, and a resource that is listed must be usable for the operations the surface offers on it.
Prefer omitting the resource from the operation's candidate set over listing it and refusing
afterwards.

Why this prevents recurrence: a listed-but-unusable resource produces a failure that is
indistinguishable from a defect, so the investigation starts at the operation instead of at the
capability declaration. The refusal is also correct in isolation, which makes the operation look
broken rather than the offer being wrong. Declaring the capability where the resource is reported
keeps the offer and the ability in one place.

## A raw error count overstates the problem it appears to measure

Trigger: the operator reported frequent provider errors, and the first measurement counted every
`"level":"ERROR"` entry. That count was dominated by channel transport noise: 562 `broken pipe` and
100 `connection reset by peer` in a single hour, emitted from `resend recorded receipt` and
`publish inventory`. Only 25 of the 726 entries in that hour were a provider error. Reporting the raw
count would have sent the investigation to the reconnect path instead of the provider seam.

Action: before reporting an error rate, group the entries by the error value and by the emitting
message, then separate transport failures from provider failures. A transport error is emitted by the
channel and describes a link; a provider error is emitted by the adapter seam and describes a
provider call. Report the two counts separately, and state which one the operator's symptom maps to.

Why this prevents recurrence: every layer logs at ERROR, so one severity covers several unrelated
failure domains. A reconnect storm produces thousands of entries and hides a handful of real provider
failures, and the largest bucket is the one that gets investigated. Grouping by value and by emitter
is what turns "there are many errors" into "these three errors are the provider problem".

## A listing and the operation it offers must read the same authority

Trigger: `history` listed 30 sessions and marked three of them `RESUMABLE=yes` with a
`resume_resource_id`, while `resume` refused the same three with
`provider session row was not found`. The cluster side was correct throughout: it minted the
resource ID, and the Endpoint gate rejected only a live target. The refusal came from the
provider's own pre-check, which read `workspace list --json --local` and therefore saw one row,
while `history` read `project list_sessions --json` and saw thirty. The two commands read
different sources: one scans `workspace/task/` for `.stdout` files and drops every row whose
metadata says `completed`, the other reads the persisted session database.

Action: when one surface offers an operation and another surface performs it, compare the two
provider commands, not the two code paths. A listing is written to be informative, so it reads
the most complete source available; an execution path is written to be strict, so it reads the
narrowest source that proves the target. Both choices are locally correct and the pair is wrong.
Then check the second-order case: a session interrupted before it wrote any output has no
`.stdout` file at all, so it is invisible to the directory scan even with the completed rows
included. Only a source that reads the persisted records can resolve it.

Why this prevents recurrence: the error names the target as missing, which sends the
investigation to the mapping, the inventory and the resource ID, all of which are correct. The
row exists, the mapping exists, and the provider command that would perform the resume can
already resolve it. The disagreement is between two reads, and neither read is in the failing
call stack. Comparing the commands is what turns "the target was not found" into "the target was
looked for in the wrong place".

## A silently ignored flag makes a partial fix look complete

Trigger: the natural fix for the authority mismatch above was to add `--all` to the existing
`workspace list --json --local` argv. `--all` is registered on the parent `workspace` parser, not
on the `list` subparser, and the top-level parser uses `parse_known_args`, so
`workspace list --all --json --local` exits 0, writes nothing to stderr, and returns 1 row, while
`workspace --all list --json --local` returns 8. The wrong placement is indistinguishable from
the right one by exit status, stderr or any log line.

Action: before trusting a flag, run both placements and compare the row count, not the exit
code. When a flag is registered on a parent parser, the argv order is part of the contract, so
pin the exact argv in a test rather than asserting that the flag appears somewhere in the slice.
This is the same class as the recorded lesson about Go's `flag` parser stopping at the first
positional argument, but the mechanism differs: Go rejects the misplaced flag, while Python's
`parse_known_args` discards it. A rejection is visible; a discard is not.

Why this prevents recurrence: a partial fix that changes nothing at runtime still passes a review
that reads the diff, because the added token is correct in isolation. It also produces exactly
the reported symptom, so the next investigation cannot tell "the fix did not work" from "the fix
was never applied". Comparing row counts across both placements is the only evidence that
separates the two.

## A duplicated validation narrows reachability without adding safety

Trigger: `resume` refused a session with `provider session row was not found`, while the provider's
own resume path would have accepted it. The cluster's `requireResumableRecord`
(`providers/topsailai/mutation_authority.go:133`) re-implemented the provider's existence and
liveness decision, and it read a narrower source. It runs in `mutationArgs`
(`providers/topsailai/mutation.go:161`) before any argv exists, so the provider CLI was never
started and its correct validation never ran. The provider's `resume_session_result`
(`cli/cli_topsailai/project_scope.py:1859`) already performs the existence check, the workspace
check, the liveness check and a late recheck at the launch boundary, and its `session_liveness`
returns `idle` when a session has no `.stdout` candidate, which is the correct answer for a session
no process holds.

Action: when a caller validates a precondition that the callee also validates, compare the two
sources before keeping both. If the callee's check is at least as strong and runs in the same
execution path, delete the caller's copy rather than widening it. Widening keeps two
implementations of one decision, and the narrower one silently wins because it runs first. Then
check what the caller's copy actually bought: here it bought a precise error code before spawning a
process, which is a message-format benefit, not a safety property. Decide explicitly whether that
benefit is worth the reachability it costs, and if it is kept, prove the two sources agree.

Why this prevents recurrence: a duplicated guard looks like defence in depth, so review accepts it
as strictly safer. It is not: the earlier guard decides, and the later guard only runs when the
earlier one allows it. A narrower earlier guard therefore removes capability while appearing to add
protection, and the failure is attributed to the callee, which is the component that never ran. The
symptom is a "not found" for something that exists, which sends the investigation to identity
mapping and storage rather than to the guard that refused it.

## A relative pathspec from a subdirectory silently returns an empty log

Trigger: while checking whether the resume path had changed, the command
`git log --oneline 7b57076a..HEAD -- providers/topsailai/` returned nothing and was
reported to the human as "the resume path has zero changes". The conclusion was wrong.
The repository root is `/TopsailAI` and the real path is
`src/topsailai_agent_cluster/providers/topsailai/`, so the relative pathspec matched no
file and git printed an empty log instead of an error.

Action: run history queries from the repository root, or use a pathspec that is correct
relative to the current directory. When a `git log` with a pathspec returns nothing,
confirm the path resolves before treating the empty result as evidence: `git ls-files
<path>` must list files, and `git rev-parse --show-toplevel` must name the root the
pathspec is relative to.

Why this prevents recurrence: an empty log is indistinguishable from "no changes", and
both are plausible answers to the question being asked. The failure is silent in the
direction that matters: it confirms the hypothesis instead of challenging it, so a wrong
conclusion is reported with confidence. The same trap applies to `git diff` and
`git show` with a pathspec, and to any tool whose "no output" means both "nothing found"
and "nothing searched".

## A whole-repository archive is not a project snapshot

Trigger: the first clean snapshot was created with `git archive HEAD | tar -x -C
.tmp/ac-clean-b33157dc` run from the repository root. The extracted tree contained
`ASSETS`, `pyproject.toml` and `uv.lock`, which belong to a sibling project, and none of
`internal`, `providers` or `src`. The build would have failed or, worse, built the wrong
project.

Action: when the project is a subdirectory of the repository, archive that subdirectory
and strip the leading path components: `git archive HEAD src/topsailai_agent_cluster |
tar -x -C <dest> --strip-components=2`. Then confirm the extracted tree contains the
project's own files before building.

Why this prevents recurrence: `git archive HEAD` from the root is the obvious command and
it succeeds, so the mistake is invisible until a build fails on a missing file. The
extracted tree looks like a valid project because it is a valid project, just not the one
being packaged. Checking for a known project file such as `go.mod` or `internal/` is what
distinguishes the two.

## A package upgrade does not change a path that the configuration spells out

Trigger: the provider package installs to a versioned directory,
`/opt/agent-cluster/providers/topsailai/<version>/`. The site `node.conf` names that
directory in `ADAPTERS.command`. Installing the new provider package therefore created a
new directory while the running configuration still pointed at the previous one, so the
Endpoint would have kept invoking the old binary with no error and no visible symptom.

Action: before packaging, rewrite every configuration value that spells out a versioned
path, and verify the packaged value by extracting the file from the `.deb` and reading it
back rather than trusting the source file. After deployment, confirm two things per node:
the provider directory contains only the new version, and `ADAPTERS.command` names that
same directory.

Why this prevents recurrence: the package manager owns the files it installs, not the
configuration that refers to them, so a versioned install path and a configured path
diverge silently on every upgrade. The failure is fail-open in the worst way: the old
binary still works, so the Endpoint reports healthy while running the previous release,
and the only evidence is a directory listing nobody checks.

## A pathspec commit takes the working tree, so hunk-level staging is discarded

Trigger: `adapter.go` contained one hunk of mine and one hunk from a concurrent agent. I
staged only my two hunks with `git apply --cached`, verified the staged diff contained
exactly them, and then ran `git commit -m "..." -- <paths>`. The pathspec form commits the
**working tree** content of those paths and ignores the index, so the foreign hunk was
swept into my commit while the staged version I had verified was never used. The
verification was real and it certified the wrong thing.

Action: when a file contains hunks from more than one author, never pass a pathspec to
`git commit`. Stage the exact hunks, confirm `git diff --cached` contains only them, and
then commit with no pathspec so the index is what lands. If a pathspec is unavoidable,
verify the result with `git show <commit> -- <file>` afterwards, because the pre-commit
`git diff --cached` check cannot detect this mistake.

Why this prevents recurrence: the two forms look interchangeable and the pathspec form is
the one that feels safer, because it names exactly the files being committed. The failure
is silent in the direction that matters: the commit succeeds, the file list is correct, and
only the hunk content is wrong. The pre-commit check passes because it inspects the index,
which is not what the pathspec form reads. This is the same class as the recorded lesson
about a green test proving nothing until it has been seen to fail: the check and the
behaviour live in different places, so a passing check certifies nothing about the commit.

## A branch that other agents commit to cannot be rewritten to fix your own commit

Trigger: after the pathspec mistake above, the corrected commit was built with
`commit-tree` and the branch was moved with `update-ref`. The update was rejected because
the branch had advanced: two other agents had committed on top of mine in the meantime.
Rewriting my commit would have required rewriting theirs, so the foreign hunk stayed in
history and only the content of the final tree could be verified.

Action: before planning any history rewrite, check whether the branch has descendants with
`git merge-base --is-ancestor <my-commit> HEAD` and `git log --oneline <my-commit>..HEAD`.
If it does, do not rewrite. Verify instead that the final tree is correct, and report the
attribution defect to the human rather than repairing it. Also clear any index entry that
was prepared for the abandoned rewrite, because a stale index blob silently reverts the
other agent's change the moment someone commits it.

Why this prevents recurrence: a shared branch moves under you, and the window between
building a replacement commit and moving the ref is long enough for another agent to
commit. The rewrite is safe only when the commit is still the tip, which is a condition
that must be checked at the moment of the rewrite rather than assumed from an earlier
observation. Leaving a prepared index entry behind is worse than the original mistake,
because it converts a wrong attribution into a silent revert of someone else's work.

## A clean status on your own edited file can mean a foreign commit already took it

Trigger: after editing `internal/adapter/genericcli/adapter.go` to pass `requireGeneration=false`,
`git status` listed every other file of the change but not that one. The natural reading was "the edit
was lost", and the summary was about to claim a change that the diff did not contain. The edit was in
fact already committed: another agent's unrelated commit `08d89ac2` had swept the file in, so HEAD
contained the fix and the working tree had nothing left to show.

Action: when a file you edited is absent from `git status`, do not conclude the edit was lost and do
not re-apply it. Read the file to confirm the intended content is present, then run
`git log -S '<a distinctive string from your change>' -- <path>` to find which commit carries it. If a
foreign commit took it, verify the content is correct and report the attribution defect instead of
re-committing. Then check the index separately with `git diff --cached -- <path>`, because a foreign
staged change can revert the very line that HEAD already has correctly.

Why this prevents recurrence: `git status` compares the working tree against the index, so it answers
"is there anything left to commit", not "is my change present". In a shared workspace those two
questions diverge in both directions: a foreign commit can absorb your edit, and a foreign staged
change can revert it while the working tree still looks right. Re-applying a change that HEAD already
contains produces a no-op diff that hides the real state, and trusting the index produces a commit
that silently undoes your own fix. Reading the file plus `git log -S` is what distinguishes "lost",
"already committed" and "staged for revert".

## A test that indexes a shared request slice assumes an order the runtime does not guarantee

Trigger: `make test-unit-cli` failed once with
`TestUnitSendAutoFollowUsesTheTenLineBudget: automatic follow maxLines=300 want=10`, while the same
test passed in isolation, passed 8 consecutive times with `-count=8`, and passed at HEAD in a detached
worktree. The value 300 is the REPL default, not the 10 the send path passes
(`internal/tui/interactive_ops.go:600`). The scenario runs `cd` then `send`, and both arm a tail:
`cd` arms the REPL default at `interactive_ops.go:79`, `send` arms 10 at `:639`. The helper
`actionFollowRequests` (`send_auto_logs_test.go:84-90`) returns `requests[1:]`, which assumes the `cd`
tail is always recorded first. When the two asynchronous streams start in the opposite order, the
assertion reads the `cd` tail and reports 300.

Action: when a test filters a shared slice by position, ask what guarantees that position. Here nothing
does: both tails are armed by separate goroutines, so the slice order is a scheduling outcome. Select
the request by a property that identifies it, such as the armed intent's own budget or the step that
armed it, instead of by index. When a test fails once and then passes repeatedly, do not close it as a
flake: read the failing value and find which producer emits it, because a value that belongs to a
different code path is the signature of a positional assumption rather than a timing accident.

Why this prevents recurrence: a positional filter is invisible in review because the slice really does
contain the expected request, just not always at that index. The failure is rare, so it is dismissed as
noise, and the test keeps certifying the wrong element on every run where the order happens to match.
Naming the producer of the unexpected value is what turns "flaky test" into "the test asserts a
different object than it names".

## Widening one command's scope breaks assertions that belong to another command

Trigger: `logs` was made available in workspace scope by changing one line of the scope matrix. The
change was correct and the `logs` tests were updated, but four tests still failed, and none of them
was about `logs`: `TestSendIsUnavailableOutsideSessionScope`,
`TestSendPrefixIsRejectedOutsideSessionScope`, `TestHelpOverviewKeepsScopeRestrictions` and
`TestUnitCBatch2PrefetchedHelpQuit`. Every one of them embeds the rendered sentence
`command "send" is unavailable in workspace scope; available commands: list, endpoints, cd, ...`,
which lists *every* workspace command. Adding `logs` therefore changed the refusal text of `send`.

Action: before changing a command's availability, grep for the rendered availability sentence rather
than for the command name. The string to search is `available commands`, because that phrase appears
in the refusal of every command that is unavailable in some scope, so one command's availability is
pinned inside other commands' tests. Update those copies in the same unit, and assert the sentence
exactly rather than with `Contains` on the command name, because a `Contains` check on `logs` passes
as soon as the help body mentions it while the refusal sentence still omits it.

Why this prevents recurrence: the scope matrix is a single source of truth, so it looks like one edit
with one consequence. The rendered sentence is a *derived* value that is copied into unrelated tests,
so the blast radius is not the command that changed. The failures also read as unrelated: a `send`
test failing while `logs` is being widened looks like a concurrent edit or a pre-existing defect, and
the tempting response is to investigate `send`. Searching for the derived sentence instead of the
command name is what turns "four mysterious failures" into "four stale copies of one string".

## A failure message's line number is the assertion site, not the row to edit

Trigger: updating the `list` digest pin in `unit_c_start_parse_test.go`, the failure reported
`unit_c_start_parse_test.go:195`. The pin table's rows sit above that line, and the `list` row was
assumed to be at 186 without reading the region. Line 186 was the `start` row, so the overwrite
replaced the `start` digest with the new `list` digest and left the old `list` row in place. The
table then held two `list` rows and no `start` row, which still compiled and still passed the
`list` case, so only the `start` case would have failed later.

Action: a line number printed by a test failure identifies the assertion that failed, never the
fixture row that needs editing. Locate the row with `grep -n` on its own content, such as the
command name or the old digest, and print the region before replacing it. When a table row is
replaced, re-read the whole table afterwards and confirm the row count and the order are unchanged,
because a duplicated row and a missing row are both invisible to a build.

Why this prevents recurrence: the failure line and the edit target are two different coordinates
that happen to live in the same file, and the failure line is the one that is conveniently already
in the terminal. Reading the row by its content makes the identity of the row the thing being
matched, so an offset guess cannot silently address a neighbouring row.

## A liveness timer must never share a goroutine with the work it is timing

Trigger: an Endpoint running a long Provider command declared the Server unhealthy and tore the link
down while the Server answered every heartbeat on time. `channelLoop` is the only reader of the
connection and ran every business handler inline, so a command bounded only by its own 120s deadline
sat in front of the heartbeat acknowledgement. The acknowledgement wait is 3s and the unhealthy window
is 30s, so any command longer than 30s guaranteed the unhealthy decision. The Server meanwhile showed
the Endpoint as `online` throughout, because its own `LastSeen` kept advancing.

Action: dispatch business handlers outside the read loop and keep the loop to pure in-memory
bookkeeping, so the acknowledgement path never queues behind a command. Verify the concurrency
premises before moving work off the loop rather than after: the websocket library documents that every
method except `Reader` and `Read` is safe to call concurrently, the executor guards its lock map and
serializes per target, the store runs one connection so journal writes are serialized, and the adapter
scheduler already bounds concurrency per class. Reuse the pattern the codebase already had for
`startFollow` instead of inventing a second one, and track the goroutine with the service wait group so
shutdown still waits for in-flight work.

Why this prevents recurrence: a liveness timer measures whether the peer is alive, so it must never
measure how long local work takes. Sharing one goroutine silently redefines the measurement, and the
symptom appears on the wrong side: the Endpoint reports the Server dead while the Server reports the
Endpoint alive, so each side's evidence contradicts the other and neither log alone explains it. The
same shape exists in the other direction, where the Server's `readLoop` calls `OnFrame` and `OnReceipt`
inline and both write SQLite, so a slow inventory commit delays the acknowledgement the Server owes the
Endpoint. Any single-reader loop that also performs durable work has this defect.

## A single-reader loop that also persists has the same defect in both directions

Trigger: a liveness timer fires on the wrong side, or a peer reports its partner dead while the partner
reports it alive, and the loop that reads frames also performs durable work.

The Endpoint fix above removed the defect from the Endpoint's read loop. The Server's `readLoop` had the
identical shape: it called `OnReceipt` and `OnFrame` inline, and both write SQLite, so a slow inventory
commit delayed the heartbeat acknowledgement the Server owed the Endpoint. The Endpoint counts
unacknowledged heartbeats and closes the connection after 30 seconds, so the Server's own persistence
latency appeared as an Endpoint-side reconnect loop while the Server still showed the Endpoint as
`online`. Fixing one direction does not fix the other; the shape has to be checked on both sides.

Action: give each peer a bounded business queue drained by one worker goroutine, answer the heartbeat
inside the read loop, and never queue the heartbeat. Queueing it is the subtle mistake: a heartbeat every
few seconds would fill a bounded queue during a stall and disconnect the very peer the design protects.
Keep one worker per peer so arrival order survives, because a receipt and the inventory that follows it
are causally related. Make a full queue close the connection rather than block the loop or drop the
frame, since a peer that cannot absorb its own inbound frames is already unhealthy and reconnecting is
honest while dropping leaves state silently inconsistent. Signal the worker to stop instead of joining
it: waiting for a worker blocked in a database write reintroduces the stall being removed. Guard the
worker with an authority check, because a superseded connection's worker can otherwise write stale state
over the connection that replaced it.

Why this prevents recurrence: the amplifier is what makes the defect reachable, and it lives in the
persistence layer rather than the loop. One connection with `journal_mode(DELETE)` and a 30 second
transaction budget means a single long transaction can hold the only connection for exactly the
Endpoint's unhealthy window, so the defect is not theoretical. Check the persistence layer's worst-case
hold time against the peer's liveness window whenever a loop both reads frames and writes durably; if the
hold time can reach the window, the loop is a liveness bug regardless of how fast the average write is.

## A test that reuses the loop context as the write context races the library's own close

Trigger: a heartbeat or keepalive test fails intermittently with `use of closed network connection`, and the
failure disappears when the test runs alone but returns when the whole package runs.

`TestRunHeartbeatKeepsAcknowledgedServerHealthy` built its loop context with
`context.WithTimeout(ctx, 600*time.Millisecond)` and then asserted `client.Ready()` after `RunHeartbeat`
returned. `RunHeartbeat` passes that same context into `SendHeartbeat(ctx)` and from there into
`wsjson.Write(ctx, ...)`. `coder/websocket` v1.8.14 `conn.go` `setupWriteTimeout` registers
`context.AfterFunc(ctx, func(){ c.clearWriteTimeout(); c.close() })`, so the moment the loop context expires
the library closes the socket. The assertion then raced that asynchronous shutdown: sometimes `Ready()` was
still true, sometimes the reader had already detached.

Action: assert readiness while the loop is still running. Use `context.WithCancel`, run `RunHeartbeat` in a
goroutine, sleep past several beat intervals, assert the unhealthy counter and `Ready()`, then cancel and
check the loop returned `context.Canceled`. Never let the loop context expire as the way to stop the loop
when that context also reaches a write.

Why this prevents recurrence: the probe showed eleven successful beats, then `READ_ERR ... use of closed
network connection` with `ctxErr=<nil>`, then `SEND_HEARTBEAT ctxErr=context deadline exceeded`, with no
`MARK_UNHEALTHY` and no `CLIENT_CLOSE`. A close that arrives while the read context is still alive cannot be
ours, so the only remaining owner is a `context.AfterFunc` on another context. Inserting a 50 ms sleep before
the assertion made the test fail 4/10 when run alone, which proves the race rather than a logic error. The
fixed test still has teeth: breaking `awaitHeartbeatAck` makes it fail 3/3.

## A follow frame must not enter the bounded business queue

Trigger: a follow or tail test fails with `write: connection reset by peer`, and the Server log shows
`SRV_QUEUE_FULL type=output_chunk`.

`readLoop` dispatched follow frames with `s.deliverFollow(peer, frame)` and then fell through into
`enqueueBusiness`. A follow tail is one frame per record, so a 300-line tail offers 300 frames to a queue
that holds 16, and the overflow branch calls `peer.Conn.CloseNow()`. An ordinary tail therefore became an
`endpoint_offline` failure on a healthy Endpoint. Queueing bought nothing either, because the worker's
`OnFrame` hook ignores every frame that is not an inventory report.

Action: `continue` after `deliverFollow` so a fully handled frame never reaches the business queue. Do not
raise `businessQueueDepth` to absorb it: a depth of 512 made the pair pass 20/20, but that only hides the
missing `continue` and leaves the queue carrying frames nobody reads.

Why this prevents recurrence: the queue exists to bound work that can block on persistence or a network
write. A frame already delivered synchronously has no such work left, so admitting it converts a healthy
stream into a disconnect. Any dispatch branch that fully handles a frame must end with `continue`, and the
queue depth must never be tuned to compensate for a frame that should not be there.

## A disconnect assertion must poll the server-side cleanup, not read it once

Trigger: a test closes a peer from the server side and then asserts that the peer is gone from `Server.Active`.

Root cause: `enqueueBusiness` calls `peer.Conn.CloseNow()` and only then returns false, so `readLoop` returns
and its `defer s.remove(peer)` deletes the peer from `Active`. The client observes the read error as soon as
`CloseNow` lands, which is before the deferred cleanup runs on the server goroutine. A test that reads
`Active` once immediately after the read error therefore races the cleanup and fails intermittently.

Detection failure: the test passed almost always, so the race looked like unrelated flakiness. It reproduced
at roughly 2.5% over 200 runs, and only when the assertion was left as a single read. Instrumenting the
production path with file logging made it pass 100/100 because the added I/O latency widened the window past
the race, which is why the probe initially "proved" the opposite.

Action: poll `Active` with a bounded deadline instead of reading it once. Prove the fix by widening the window
deliberately: inserting a 5 ms sleep at the top of `remove` made the single-read form fail 20/20, confirming
the ordering rather than a genuine leak.

Why this prevents recurrence: a client-visible disconnect and the server-side bookkeeping that follows it are
two different goroutines. Any assertion about post-disconnect server state must wait for that state with a
deadline, and a probe that adds I/O to the path under test must not be trusted to reproduce a timing race.

## A capability gate must probe the layer that performs the work

Trigger: `agent.stop` was advertised, admitted, confirmed and then always failed with
`safe_signal_unsupported`. The Provider gate (`providers/topsailai/platform_linux.go:39`) probed the
kernel pidfd syscall for its own PID and passed, so `agent.stop` stayed in the descriptor. The signal
is sent by the Python business CLI, which needs `os.pidfd_open` and `signal.pidfd_send_signal`
(`cli/cli_topsailai/workspace_kill_cli.py:142-147`), and the interpreter the launcher selects through
`uv run` exposes neither. The kernel could do it; the interpreter could not.

Action: when a capability gate decides whether an operation is advertised, identify the component that
actually performs the work and probe that component's own capability, not a lower layer that merely
makes it possible. Here the Go Provider probes a syscall while a Python child sends the signal, so the
probe answers a different question than the one the gate is asking. Prefer letting the performing
component report its own capability in `describe` and intersecting it, because only that component can
answer truthfully. Then verify the gate on the real deployment path: run the configured executable the
way the launcher runs it, and confirm the advertised set matches what the operation actually does.

Why this prevents recurrence: a lower-layer probe is the natural implementation because it is local,
cheap and testable, and it passes on every host where the kernel is modern enough. The gap is invisible
in review because the probe is correct about what it measures, and it is invisible in tests because the
test injects a platform value rather than running the real interpreter. The failure then appears only
at execution time, after the operator has already been told the capability exists, which is the worst
place for a capability claim to be wrong. Probing the performing layer, or letting it report itself,
makes the advertised set and the achievable set the same fact.

## A single failure message for a family of errors misdirects the investigation

Trigger: `workspace kill` reported `error_code: safe_signal_unsupported` together with
`message: No exact verified session target` (`cli/cli_topsailai/workspace_kill_cli.py:203`). The code
was raised at line 147, after `_resolve_target` had already found a live, generation-matched process,
so the message described the opposite of what happened. The operator's report quoted the message, which
pointed at target selection and generation mapping rather than at the interpreter.

Action: when one handler maps several distinct error codes onto one exit path, check whether the
message is still true for every code. A message that names a cause must be derived from the code, not
fixed for the branch. Keep the machine code precise and let the human message name the same condition,
because the message is what the operator quotes back in a bug report.

Why this prevents recurrence: a fixed message is written once for the first error that needed it, and
later codes are added to the same branch without revisiting the text. The code stays correct, so every
test that asserts the code passes, and only the human-readable half is wrong. The cost is paid by the
next investigation, which starts from a false premise supplied by the tool itself.

## A guard that counts directory levels encodes a position, not an identity

Trigger: moving each provider's sources into a `src/` subdirectory silently invalidated six guard tests
that located sibling files by counting `..` segments: `../../conf/...` for the shipped catalog,
`../../../topsailai/cli/...` for the provider business CLI, `../../go.mod` for the module boundary and
`../../protocol/...` for a schema. Every one of them still compiled and still ran. Each would have read
a file one level away from the intended one, and a guard that reads the wrong file passes while proving
nothing.

Action: when a test or tool needs a file outside its own package, resolve it by identity rather than by
depth. Walk up from the working directory until a `go.mod` declares the expected module name, then
build the path from that root; for a sibling project, resolve the cluster root first and take the
sibling from there. Put the resolver in one small file per module so every guard shares it, and prove
the resolver by breaking it: corrupt the module name constant and confirm the guards fail with a
locating error, then restore it. A resolver that has never been seen to fail is indistinguishable from
a resolver that returns the wrong path.

Why this prevents recurrence: a depth-counted path is correct only for one directory layout, and it
fails in the direction that hides itself. Adding a directory level does not produce a compile error or
a missing-file error, because the wrong path usually still exists: `../../conf` resolves to a real
directory one level off, so the read succeeds and the assertion runs against the wrong content. The
same trap applies to any relative path computed from `runtime.Caller` depth, to `filepath.Join` chains
built from a hardcoded `..` count, and to shell scripts that `cd ../..` before reading a file. Identity
resolution makes the layout change a non-event, and the deliberate break is what separates "the path
resolves" from "the path resolves to the file I meant".

## A test fixture that no target builds is dead code that still compiles

Trigger: while classifying `tests/` by owner, two fixtures (`topsailai_fixture`, 382 lines, and
`topsailai_session_info_fixture`, 45 lines) turned out to have no build entry point in any Makefile,
script or Go helper. `git log -S` traced the loss to `facaae86`, which removed the harness paths when
the old TopsailAI adapter was deleted. Both still compiled cleanly, which is exactly why nothing
failed and nobody noticed for many commits. The only remaining references were comments describing
them in the past tense, one of which said "a binary the harness no longer builds".

Action: before moving or reorganising a test artifact, prove it has a consumer. Search the build
entry points for its path, not for its name: a fixture can be named in prose, in a comment and in an
issue record while no target builds it. Then check whether it still compiles, because a compiling
fixture looks alive. If no target builds it, treat it as dead code and delete it rather than
relocating it, since a move preserves the defect and makes it look maintained.

Why this prevents recurrence: a fixture is a program, so it keeps compiling after its consumer is
deleted, and a compiler is the only check most people apply. The failure is silent in the direction
that matters: the suite is green, the file is valid Go, and the folder looks complete. Relocating it
into a provider workspace would have made it worse, because the new location implies ownership and
maintenance that nobody provides. The tell is a comment written in the past tense about a binary the
harness "no longer builds": that sentence is a defect report nobody acted on.

## A failover feature configured with one candidate has nothing to fail over to

Trigger: the DR test stopped the primary Server and the CLI printed a raw
`dial tcp 172.19.1.1:53680: connect: connection refused` instead of falling back. The failover code
was correct and fully tested. `AGENT_CLUSTER_CLI_SERVER_PROFILE` was set to the single name
`primary`, and `parseServerProfileGroup` (`src/main/agent-cluster-cli/cli_server_profile.go:118`)
treats one name as a group of one, which is deliberate: it keeps an existing single-Server deployment
unchanged. So the deployment had one candidate and the feature had nothing to choose between.

Action: when a failover or retry feature is deployed, verify the configured candidate list has more
than one member before testing the failure path. Read the resolved list, not the variable: a
comma-separated group and a single name are the same variable with different arity, and the arity is
what the feature needs. Here the fix was `primary,secondary`, and the same command then reported
`server "primary" skipped: unreachable` followed by `using server profile "secondary"`.

Why this prevents recurrence: a group-of-one is a supported configuration, so nothing rejects it and
no test fails. The feature is then present, tested and inert, and the failure it produces is the
generic transport error the feature exists to replace. The tell is that the error names a URL rather
than a skipped candidate: a working failover always reports which candidate it skipped, because
skipping is the decision it made.

## A fallback peer left in the old auth mode turns a failover into a credential error

Trigger: after the CLI switched to HMAC, stopping the primary made the CLI fall back to the secondary
and receive `401 unauthorized: authentication required`. The credential was correct. The secondary
Server was still `AUTH_MODE=bearer` while the CLI signed its request, so the fallback reached a peer
that could not verify the new scheme.

Action: when a credential scheme changes, treat every peer that can answer a request as a boundary to
migrate, including peers that are only reachable on a failure path. Enumerate them from the failover
configuration rather than from the list of machines currently serving traffic, because a standby
receives no requests until the moment it matters. Verify each peer independently with a positive call
and a wrong-secret call before declaring the migration complete.

Why this prevents recurrence: the standby is invisible during normal operation, so every check that
exercises the active peer passes while the standby stays on the old scheme. The failure then appears
only during the incident the standby exists for, and it presents as an authentication problem, which
sends the investigation to the credential rather than to the mode. A wrong-secret probe on each peer
is what distinguishes "this peer verifies HMAC" from "this peer is reachable".

## A note that forbids an action must be checked against the exact command, not the intent

Trigger: the runbook states twice that only the Endpoint processes inside `ai-dev` and
`topsailai-dev` may be restarted, and that the containers themselves must not be restarted
"because recreating them would kill the Agents that share their lifecycle boundary". While
resetting the connection generation after a Server recreate, the command
`for c in ai-dev topsailai-dev; do docker restart "$c"; done` was run anyway. It killed Agent
`wa-d3ea717b411f` (pid 1783182) mid-turn: its last event was `tool_call.end
file_tool-read_file_lines` at `07:28:48.309845`, and its meta still says `status: running` with
`end_ts: null`, so the session is dead but recorded as alive.

Action: before running any lifecycle command against a container that hosts Agents, quote the
forbidden action from the note and compare it to the literal command. Here the note forbids
`docker restart` and a container recreate, and permits only
`docker exec <c> .../agent-clusterctl -c conf/endpoint/node.conf restart`. The permitted form
restarts one process inside the container; the forbidden form restarts the container and every
process in it. When the goal is "reset the connection generation", the permitted form achieves it,
so the forbidden form was never necessary.

Why this prevents recurrence: the intent ("restart the endpoint") and the command ("restart the
container") differ by one word and both produce a working Endpoint, so the outcome looks correct
while the collateral damage is invisible. The damage is also silent in the direction that matters:
the Endpoint reconnects and reports healthy, and only a session file that stops mid-turn records
that an Agent died. Checking the literal command against the note's literal prohibition is what
separates "I restarted the thing I meant" from "I restarted the boundary that owned it".

## `RestartCount` does not prove a container was never restarted

Trigger: asked whether `ai-dev` had been restarted, the answer given was "no", citing
`RestartCount=0` and `RestartPolicy=no`. Both were true and both were irrelevant: `RestartCount`
counts only restarts performed by the restart policy, so a manual `docker restart` leaves it at
zero. The container had in fact stopped and started 0.46 s apart, which `FinishedAt` and
`StartedAt` showed directly, and the container log's last line was
`Shutting down, got signal: Terminated`.

Action: to prove a container was not restarted, compare `State.StartedAt` against `State.Created`
and against the host's boot time, and read the container log's last line for a shutdown marker.
`RestartCount` answers a different question and must never be used as evidence of "never
restarted". When the container's own log ends in a termination message, the container stopped,
regardless of the restart policy.

Why this prevents recurrence: `RestartCount=0` reads like a clean bill of health and it is the
field that looks purpose-built for the question, so it is the first thing consulted and the last
thing doubted. The two fields that actually answer the question sit beside it and are ignored
because they look like timestamps rather than evidence. A wrong "no" is worse than no answer: it
closes the investigation that would have found the killed Agent.

## A rollout checklist that names roles misses the per-node instances of a role

Trigger: the HMAC cutover checklist named three boundaries — Server, Endpoint, CLI — and I switched
gd-dev's Server verifier and Endpoint verifier but left gd-dev's CLI caller on the pre-HMAC form. That
CLI then rejected its own credential locally, before sending anything:
`server credential is not in key_id.secret form required by hmac mode`. The other three nodes were
correct, so every check I ran on the host I was working on passed.

Action: when a checklist names a role, enumerate the instances of that role before executing. Here the
role "CLI" has four instances, one per node, and all four environment files live at the identical path
`/root/.topsailai/.topsailai_agent_cluster.env`, which is exactly why reading "the CLI environment file"
on one host looks like a complete check. Write the instance list into the checklist itself, and verify
each instance by its own rendered output rather than by a shared probe.

Why this prevents recurrence: a role name reads as a single thing, so a checklist that is correct at the
role level is silently incomplete at the instance level. The identical path removes the last cue that
would prompt a second look, and the nodes that are skipped are the ones that serve no traffic during
normal operation, so their failure surfaces only during the incident they exist for.

## A credential rejection that exits zero certifies a CLI that did nothing

Trigger: the gd-dev CLI printed `server credential is not in key_id.secret form required by hmac mode`
and exited **0**. Any script testing `$?` reported a working CLI while the CLI had sent no request at
all.

Action: verify a CLI by its rendered output, never by its exit status alone. When a CLI prints a
diagnostic and exits 0, treat the exit code as a defect rather than as evidence of success, and check
the exit code of the failure path explicitly when adding a credential or configuration validation.

Why this prevents recurrence: the message reads like usage text, which is conventionally paired with a
zero exit, so the pairing looks normal. The exit code is the cheapest automation guard, so a zero exit
propagates into every script and check that trusts it, and the CLI's own silence is indistinguishable
from a command that legitimately produced no rows.

## A Server-side projection cannot prove an Endpoint-side check

Trigger: while verifying the HMAC cutover, `agent-cluster-cli endpoints` was used as the negative probe
for the Endpoint boundary. It passed with a deliberately wrong Endpoint secret, which looked like the
policy was not verifying. It was not verifying because it was never reached: `endpoints` renders the
Server's persisted inventory and never contacts an Endpoint, so the wrong credential was never used.

Action: before using a probe as evidence for a boundary, trace which component consumes the credential.
A Server-side projection proves the Server boundary only. Use a live provider read such as
`history <endpoint>` to reach the Endpoint policy, and state in the evidence which component the probe
actually exercised.

Why this prevents recurrence: a probe that passes for the wrong reason is worse than no probe, because
it certifies a check nobody performed. The failure direction is the dangerous one: a correct
implementation looks broken, and the natural response is to weaken the verifier that was never
consulted.

## A seam named after a provider command inherits that command's projection

Trigger: the human reported that `info`'s `provider_metadata` has no `metafile` field while the
TopsailAI provider does provide it. The field exists, but in a different provider command.
`provider_metadata` is defined as the provider's `session info --json` record
(`providers/topsailai/src/query.go:621-664`), which is built from the session database
(`src/topsailai/cli/topsailai_session_info.py:105-150`) and has no `metafile` key. `metafile` is a
`workspace list --json` item field built from the row's on-disk `{session_id}.{pid}.session.meta`
record (`src/topsailai/cli/cli_topsailai/core.py:1561-1579`). Both commands describe the same
session and expose different field sets, so the seam is faithful and the expectation was wrong.

Action: when a field is missing from a provider seam, read the provider command the seam is defined
against before looking for a drop in the forwarding chain. Then run that exact command and the
command that does expose the field, and compare their key sets. A seam that forwards verbatim cannot
lose a key, so a missing key means the source never sent it. When the two commands differ, decide
which one the seam means rather than merging them: one seam carrying two sources makes the field's
origin unknowable.

Why this prevents recurrence: a verbatim seam looks like the obvious place for a dropped field, so
the investigation starts at the forwarding code and every layer there is correct. The provider
exposes the field somewhere, which makes the seam look broken. The two commands are both plausible
sources for "the session record", and nothing in either one names the other, so the difference is
visible only by running both and comparing keys.

## A seam's content is the Provider's, and a Cluster-side tidy-up is a defect

Trigger: while evaluating whether `topsailai runtime info` could replace the two reads behind
`session.detail`, the Provider's new document carried both a session record and a `runtime` object,
so the two seams `provider_metadata` and `provider_runtime` would overlap. Two fixes were proposed,
and both were Cluster-side content edits: "drop the `runtime` key from `provider_metadata`" and
"teach the TUI renderer to skip that key". The human rejected the direction: `provider_metadata` and
`provider_runtime` are seams, standard interfaces and contracts, what fills them is the Provider's
business, and the Cluster keeps the content verbatim without processing it at all.

Action: when two seams would carry the same object, or a seam's document looks like it needs
trimming, the fix belongs in the Provider project, never in `internal/`. `providers/<name>/` is an
independent module, so the Provider can split, merge or drop its own keys without any Cluster,
Server, schema or CLI change. The Cluster's only legitimate work on a seam is addressing: which
resource, which row, which bound. That work lives in `internal/protocol` and the adapter and never
touches the document body. Before proposing any edit to a seam's bytes, ask which project owns the
document; if the answer is the Provider, the edit is in the wrong repository.

Why this prevents recurrence: a Cluster-side tidy-up is the shortest path to a clean-looking result,
and it passes every test on the only Provider that exists, so review cannot see the defect. It makes
the Cluster a second author of a Provider document, and the two authors diverge the first time the
Provider changes its record. The failure is silent in the direction that matters: the edited document
still renders and still looks complete, and only the dropped field is missing, which nobody can see
because it is not there. The same trap applies to any seam the Cluster forwards, not only to
`session.detail`: a renderer that hides a "redundant" key, an adapter that merges two documents, and
a Server that re-encodes a forwarded payload are all the same defect wearing different clothes.

## A convenience read added to a shared helper lands on the hot path of every caller

Trigger: to carry the opaque Provider slot into a follow intent, `armFollowStream` was given a
synchronous `SessionReadIdentity` call. That helper is shared by the explicit `logs -f` command, the
post-send automatic tail and the post-start tail, so the read was added to the send path as well. The
send path arms its tail before forcing one collection, and the extra inventory round trip delayed that
refresh enough that `TestUnitSendAutoFollowKeepsTheForcedCollection` timed out waiting for three
automatic steps and observed only `[follow follow]`. It passed 5/5 in isolation, passed three full
package runs, and failed once in a `make test-unit-cli` run, so it first looked like flake.

Action: when a shared helper needs one more fact, check whether every caller already holds that fact
before adding a read inside the helper. Here all three callers already had the session row: two had
`session.ProviderTarget` in hand and the third had it in `state.Scope`. Thread the value through the
helper's parameters instead of re-reading it, and keep the helper free of I/O so its cost stays
predictable for every caller. When a test fails once and then passes repeatedly, compare the failing
value against the producers on that path before calling it flake: `[follow follow]` with no `refresh`
named the missing step, and the missing step was the one the added read delayed.

Why this prevents recurrence: a helper is chosen for reuse precisely because many callers share it, so
a read added for one caller's convenience is paid by all of them. The cost is invisible in the diff
because the added line is correct in isolation, and it is invisible in a focused test because the
focused test exercises one caller. Only the composed path shows the delay, and only as a timeout that
looks like timing noise. Threading the already-known value keeps the helper pure and makes the
duplicate read structurally impossible rather than merely removed once.

## A configuration key can be dead for the daemon and live for the installer

Trigger: while mapping the credential sites for a rotation, the Endpoint `AUTH_TOKEN` was reported to
the human as "dead configuration", on the evidence that `cfg.AuthToken` is consumed only by
`src/main/agent-cluster-server/main.go:188`, that the Endpoint branch of `scripts/agent-clusterctl`
never passes `--auth-token`, and that `src/main/agent-cluster-endpoint/main.go` contains zero
references to `AuthToken`. All three facts were true. The conclusion was wrong, and the human rejected
it with "endpoint的auth_token应该不是死配置，你仔细读代码".

Action: when deciding whether a configuration key is used, search the whole deployment surface, not
only the daemon that reads the same-named struct field. Here the consumers are the maintainer scripts:
`scripts/deb/postinst.endpoint:37` sources `node.conf` and passes `AUTH_TOKEN` to `cli_env_write`, and
`scripts/install-node.sh:161` does the same for a copied bundle. Both write
`AGENT_CLUSTER_CLI_SERVER_TOKEN` into the per-user CLI env file, so the key is the install-time source
of the operator CLI's Server credential on that node. Search for the literal key name across `*.sh`,
`*.conf` and the maintainer scripts, not only `*.go`, and check `scripts/lib/` for the shared writer
that consumes it.

Why this prevents recurrence: a struct field and a shell variable with the same name are two different
things, and a `grep` restricted to Go files answers only the daemon question. The daemon answer was
correct and it was the wrong question, so the evidence looked conclusive while the conclusion was
false. The failure is silent in the direction that matters: a key that the daemon ignores looks
unused, and the installer that depends on it runs once, at install time, where nobody is looking. The
tell is that the key is present in a shipped `node.conf` at all: a template does not carry a value
that nothing reads, so a key with no daemon consumer should be traced to the packaging path before it
is called dead.

## A line-range replacement that repeats its own anchor duplicates the block

Trigger: while removing the `AUTH_TOKEN` placeholder check from `scripts/make-deb.sh`, the replaced
range was `505-510` and the replacement content repeated the `if grep -q "127.0.0.1"` block that
already sat inside that range. The result was a duplicated `warn` line and an orphaned `fi`. The next
edit then removed the wrong two lines and deleted the `fi` that closed the surviving `if`, leaving a
function that `bash -n` rejected. The same class of mistake happened again in `README.md`, where a
replacement range began one line below the paragraph's first line, so the first line survived and the
replacement re-emitted it, duplicating the sentence and swallowing the opening of the next paragraph.

Action: when a replacement range covers only part of a block, the replacement must contain only the
lines that are new, never a copy of a line that is still outside the range. Before writing, print the
exact range and confirm which lines are inside it and which are outside. After every line-range edit,
run `bash -n` on a shell file or read the region back, and check the diff for a duplicated line or a
lost closing token. When a block needs several interdependent edits, replace the whole block in one
call instead of chaining edits whose line numbers shift under each other.

Why this prevents recurrence: the tool reports success either way, and a duplicated line or a missing
`fi` is invisible in the success message. Prose has no compiler, so a swallowed paragraph opening
renders as a plausible sentence and survives review. The only cheap check is reading the region back
and looking at the diff, which is exactly what the success message makes you skip.

## A named exception at one layer is not the same exception at the next

Trigger: `project.add` is the only standard mutation that carries no target. The exception had to be
added at six independent sites — `request.schema.json` (the execute base plus a new branch that
re-requires `target` for every other execute), `internal/providercli` (`validateExecute`),
`internal/adapter/genericcli` (`executionTarget`), `providers/topsailai`
(`validateExecuteRequest`), `providers/topsailai` (`validateExecuteEnvelope` in `codec.go`), and
`providers/mock` (`executeResponse`) — because each layer re-validates the contract it cannot import.
Adding it to five of six leaves the operation advertised but unreachable, and the failure appears as a
generic `invalid_request` from the layer that was missed.

The sixth site was missed in exactly that way. `validateExecuteEnvelope` runs on the real process entry
point (`serve` → `decodeRequest` → `validateRequest`), before dispatch, so the binary refused every
target-less `project.add` while the whole unit suite stayed green: every project test called
`dispatch` directly and therefore skipped the envelope check. The defect was found only by running the
built binary by hand, not by any test.

Action: when a contract gains a named exception, enumerate every layer that re-validates that contract
before writing any of them, and add the exception to all of them in one unit. Search for the existing
rejection message (`target is required`) rather than the operation name, because the message is what
each layer spells independently. Then prove reachability at the layer that actually runs first: a test
that enters through the process boundary (`decodeRequest` or `serve`), not only through the handler.
Pair it with a negative test on a different operation, so the exception cannot silently become a
general relaxation.

Why this prevents recurrence: each layer's check is locally correct and its own test passes, so review
sees six green suites and no defect. The exception is also the kind of change that looks like one
edit, because the contract document states it once. The failure direction is silent: the operation is
advertised in the descriptor, so the operator sees a capability that exists and a command that always
fails, which reads as a Provider bug rather than a missing branch in a layer nobody edited. A handler
level test cannot detect this class at all, because the handler is the layer that was already correct.
## A strict decoder refuses a field the Cluster legitimately forwards

Trigger: the `project.remove` matrix scenario failed with
`decode request: json: unknown field "provider_target"`. The Cluster forwards the opaque
`provider_target` slot verbatim for every resource-addressed operation, and the TopsailAI Provider
already modelled it, but the mock Provider's `target` struct did not. Its decoder uses
`DisallowUnknownFields`, so a request the contract permits was refused as malformed before any
behaviour ran.

Action: when the Cluster gains a standard slot, add it to every Provider's request struct in the same
unit, including test-only Providers. The mock is not a throwaway: it is the executable reference the
conformance and BDD suites drive, so a field it cannot decode makes a legitimate contract
unexercisable. Search for the decoder's strictness setting rather than for the field name, because a
permissive decoder hides the omission.

Why this prevents recurrence: the slot is optional, so every existing request still decodes and every
existing test still passes. The failure appears only on the new operation, and it presents as a
malformed request rather than a missing field, which sends the investigation to the Cluster's
forwarding code that is in fact correct.

## A test that asserts argv exactly also refuses a destructive flag nobody added yet

Trigger: `project.remove` must never delete the folder on disk, and the first version of its test
asserted only that the folder still existed after the call. That assertion passes for any argv the
Provider happens to build, so it would keep passing if a later change added a flag that deletes data
and the deletion silently failed for an unrelated reason, such as a permission error.

Action: when an operation must not have a destructive effect, assert the exact argv in addition to the
observable outcome. The argv is the only place a destructive flag can appear, so an exact comparison
refuses every flag rather than the ones the author happened to think of. Then prove the assertion has
teeth by adding a plausible destructive flag and confirming the test fails.

Why this prevents recurrence: an outcome-only assertion certifies the current behaviour of the code
under test, not the absence of the capability to do harm. The two are the same today and diverge the
moment someone adds a flag, and the divergence is invisible because the folder still exists in the
test's own fixture. Comparing argv turns "the folder survived this run" into "this Provider cannot
express a deletion".

## A long option's value can be the flag you are scanning for

Trigger: the version flag was detected by scanning raw arguments before flag parsing, and the
daemons were wired with `version.Requested(os.Args[1:], nil)`. The comment justified the nil map
with "the daemons register only long-form options, so a bare `-v` can only be a version request".
That reasoning is wrong: `--tls-certificate-file -v` names a file called `-v`, and the option is
long-form. The daemons register dozens of value-taking options (`--database-path`,
`--tls-certificate-file`, `--auth-token`, `--project-root`, `--endpoint-expiry`), so every one of
them could swallow the flag as its value and answer a version request the operator never made.

Action: when a raw scan must distinguish an option from an option's value, derive the value-taking
set from the parser's own declaration instead of passing nil or hand-listing names. Here `Load`'s
registration block was extracted into `registerFlags`, and `ValueOptionNames(role)` builds a
throwaway flag set from it and collects every flag whose value does not satisfy
`interface{ IsBoolFlag() bool }`. One declaration then serves both the parser and the scan, so a
newly added option is covered without a second list. Then prove the wiring, not only the scanner:
a test of the scanner passes with an empty set, which is exactly the defect, so each daemon got a
named `versionRequested` helper that a test can call to assert which set it passes.

Why this prevents recurrence: "only long options are registered" sounds like a structural argument
but it is a claim about spelling, and spelling has nothing to do with whether an option consumes
the next argument. The failure is silent in the direction that matters: a bare `-v` answers
correctly either way, so running the binary proves nothing, and the defect appears only when an
operator's option value happens to be `-v`. Deriving the set from the declaration makes the two
views structurally identical, and asserting the daemon's own helper is the only evidence that the
set reached the scan.
