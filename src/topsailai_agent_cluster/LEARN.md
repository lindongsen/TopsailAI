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
