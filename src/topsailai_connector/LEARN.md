---
maintainer: AI
author: DawsonLin
---

# Lessons

Project-specific lessons discovered while building the Connector: root causes,
detection failures and reusable pitfalls. Cross-project lessons belong in the
AI reflection archive, not here.

## Layout

- `internal/protocol` and `internal/security` are the only packages both
  binaries import. Keep them free of IO, otherwise the Server and the Node can
  disagree about the contract while both still compile.
- `internal/` is used instead of `pkg/` so the compiler enforces the boundary:
  the Node binary cannot import server code and the Server binary cannot import
  node code.

## Packaging

- A bundle must not bake the build host's absolute scope paths into
  `policy.yaml`. A policy requires absolute paths, and the build host's paths are
  not the user's paths, so the bundle ships an editable `scopes.txt` and its start
  script writes `policy.yaml` on the machine that serves the files. Baking the
  paths in produces a bundle that fails on the machine it was built for.
- The node id and the node credential are generated at packaging time by running
  the Node's own `id` and `credential add` commands, not by a second
  implementation in the packaging script. A second implementation is a second
  definition of the credential format, and the two will eventually disagree about
  what a valid credential is.
- `make package-windows` is a separate target rather than a variable the caller
  must remember. Forgetting `PACKAGE_GOOS` produces a Linux binary in a zip a
  Windows user cannot run, and the failure appears on their machine rather than
  on the build host.

## Path comparison

- Two paths compared for containment must be resolved by the same rule. A guard
  that compares a logical path against a physical one silently never matches, and
  a guard that never matches looks exactly like a guard that passes. This is how
  the bundle's config-overlap check was bypassed by a symlinked bundle path; see
  `issues/issue-bundle-config-overlap-bypassed-by-symlink.md`.
- `Resolve-Path` on PowerShell 5.1 does not follow a junction: it returns the
  junction's own path. A resolver that must follow links has to walk the path
  component by component and read `LinkType` and `Target` at each level, because a
  junction can sit at any level rather than only at the leaf.
- A fix that changes a resolution rule must be verified by running the case where
  the two forms differ, not by reading the diff. The first PowerShell fix was a
  no-op that read correctly.

## CLI argument order

- Go's `flag` package stops parsing at the first non-flag argument, so the CLI's
  operation name must come last. Every flag written after it becomes a positional
  argument and the command fails with a message about positional arguments rather
  than about order. `docs/API.md` had the example backwards; see
  `issues/issue-cli-example-contradicts-argument-order.md`.
- `file.list` on a scope root takes an empty `--path`, not `--path .`. The path
  grammar rejects a `.` component rather than normalising it, and `allowRoot` is
  set only for `file.list`.

## Documenting an error message

- A troubleshooting table must quote the string the program actually emits, not a
  paraphrase of it. The bundle README and the Node skill both listed
  `handshake refused`, which appears nowhere in the source; the real line is
  `level=WARN msg="channel ended" error="the server refused the handshake:
  unauthenticated"`. A user searching the log for the documented text finds
  nothing and concludes the failure is something else.
- A refusal belongs in the table of the component that produces it. The handshake
  refusal was listed under "what the start script refuses", but the script cannot
  check a `tunnel_token`: only the Server knows the right value. The script starts
  the Node, the Node dials, and the Server refuses. Documenting it as a script
  refusal sends the reader to the wrong file.
- A retry claim must be read off the loop, not assumed. The README said a refused
  handshake is not retried, while `Dialer.Run` retries every error except context
  cancellation and logs `retry_in`. The warning repeats every 5 seconds, which is
  the opposite of what the document promised.
- Verify a documented message by triggering it. Running a Node with a wrong
  `tunnel_token` against a real Server produced the exact line in one command,
  and that run is what showed the paraphrase was wrong.

## A rule stated only in prose is not implemented

- `docs/permission-design.md` said a scope must not contain the Node's config
  directory, and the enforcement checklist repeated it, but `validateScopeMapping`
  never received the config directory and so had nothing to compare against. The
  rule was documented, reviewed and unenforced at the same time. A checklist item
  is a claim about the code, so it must be traced to a call site before it is
  ticked; see `issues/done/issue-scope-may-contain-config-directory.md`.
- The consequence was narrower than "the config is readable" and still real: the
  contents were denied, but `file.list` reported the names and sizes of `identity`
  and `policy.yaml`. A partial leak is the failure mode to look for, because a
  rule that is half-implemented reads as implemented.
- A containment check needs the separator boundary, not a string prefix.
  `config-backup` and `config2` share a prefix with `config` and are not inside
  it, so the check compares `filepath.Rel` output against `..` plus a separator.
  A prefix check would refuse a legitimate sibling, which is the failure that gets
  a security rule deleted rather than fixed.

## A test fixture can encode the misconfiguration a new rule forbids

- `cmd/connector-node/main_test.go` created its scope at
  `filepath.Join(configDir, "project")`, which is exactly the layout the new
  overlap rule refuses. Adding the rule turned five passing tests red without any
  production behaviour changing. The fixture was wrong, not the rule.
- The same shape appeared in `internal/node/run_test.go`, where
  `TestOpenDeniesTheIdentityFile` pointed a scope at the config directory to prove
  the per-file deny worked. The new startup refusal makes that state unreachable,
  so the test had to be replaced rather than adjusted: it now proves the startup
  refusal, and a separate test proves the per-file deny still works for a policy
  file that legitimately sits inside a scope.
- When a new rule invalidates a fixture, decide which property the test was really
  protecting before rewriting it. Deleting the test because its setup is now
  illegal would drop the coverage the setup existed to provide.

## Verification tooling must be tested too

- `make check` reported success while the BDD suite failed, because every test
  target pipes through `| tee` and bash returns the status of the last stage.
  `SHELL := /bin/bash` was already set; `pipefail` was not. A green `make check`
  was therefore not evidence of anything, and it hid a real failure for three
  commits; see `issues/done/issue-make-check-masks-suite-failures.md`.
- The variable is `.SHELLFLAGS`, with a leading dot. A plain `SHELLFLAGS` is an
  ordinary variable that Make silently ignores, so the first attempt at the fix
  changed nothing and looked correct. `make -p` is what showed the default
  `.SHELLFLAGS := -c` still in force.
- Only `pipefail` is needed. `-e` and `-u` change nothing here, because each recipe
  line already runs in its own shell, so Make stops at the first failing line
  without help. Adding them with a plausible-sounding justification is scope creep
  in a file that decides whether anything is verified.
- The same trap catches a human: `cmd | tail -3; echo $?` reports `tail`'s status,
  so a refusal that exited 1 was recorded as `rc=0` until the command was re-run
  without the pipe. Read the exit status of the command under test, never of the
  pipeline that displays it.
- A package with source and no test files breaks `go test -coverprofile` on this
  toolchain with `go: no such tool "covdata"`, because the coverage merge step has
  nothing to merge. `cmd/connector-server` was the only such package. The fix is a
  test file, not an environment change: the missing tool is a symptom of a package
  nobody tested.
- A suite that cannot observe a class of defect reports success for that class.
  `make check` ran seven stages and none used `-race`, while the Server keeps a
  routing registry behind a mutex and the Node publishes a regenerated identity
  from a polling goroutine. Green meant "no race was observed by a build that
  cannot observe one"; see `issues/done/issue-no-race-detection-in-check.md`.
- Coverage and e2e are not substitutes for instrumentation. Coverage measures
  which lines ran, not whether two goroutines touched one word, and an e2e script
  observes only the answers, which a racy registry returns correctly until it
  does not. Three reassuring signals (green check, 89.9% coverage, real-process
  e2e) all pointed the same wrong way.
- Prove the detector is active before trusting a green race run. `go tool nm` on a
  `-race` test binary shows `racefuncenter`/`__tsan` symbols and the same binary
  built without the flag shows none, and a throwaway module with a deliberate
  unlocked counter must fail with `DATA RACE`. A race run that passes proves
  nothing until one of those two checks has been done.
- The race stage is a separate target, not a flag on `test-unit`. `-race` needs
  cgo and roughly doubles the run time, and instrumenting `coverage` would change
  the profile so the percentage stops being comparable with earlier runs. A
  separate target also names the class of defect it covers, which is what the
  original file lacked: nothing stated which classes the suite was responsible
  for, so a new class had no place to be added.
- The stage is incomplete in a way worth stating: the Node process the integration
  suite spawns is built without `-race`, so only in-process code is instrumented.
  A limitation written in the target's comment is reviewable; one discovered later
  by someone trusting the target is not.

## A documented command is a claim that must be executed

- The README "First run" block documented four commands and none of them ran:
  `-listen` and `-server` are not flags on either binary, `file read` is not a
  subcommand, and the CLI flags must precede the operation name. See
  `issues/done/issue-readme-first-run-commands-do-not-run.md`.
- The cause is writing documentation from the design intent instead of from the
  implemented interface. `runServer` and the Node's `run` register no flags at
  all, so a flag-shaped example cannot be right no matter how natural it reads.
- The same wrong CLI shape had already been fixed in `docs/API.md` and left in
  `README.md`. A fix scoped to one file fixes one file, not the claim: when a
  defect is a wrong example, search every document for that example.
- Execute a documented command before publishing it, and again after changing the
  interface it names. A README that looks right but was never run is the same
  class of defect as a test that was never run.

## A cleanup script is a destructive program and must be written like one

- A cleanup script deleted `C:\Users\Administrator\Documents` in full, including
  an unrelated pre-existing folder, because a path was built by concatenation
  inside an array literal: `"C:\Users\Administrator\Documents\" + $name`. The
  trailing backslash escaped the closing quote, the `+ $name` was dropped, and
  the array held the parent directory. See `issues/91critical_issues.md`.
- `Remove-Item -Force` bypasses the Recycle Bin, so the deletion had no recovery
  path. The host had no shadow copies and no restore points.
- The log line looked correct because the non-ASCII child name was invisible in
  the console, so `removed C:\Users\Administrator\Documents\` read as if it named
  the child. A deletion log must print the resolved path and its codepoints, not
  a name the console may render as nothing.
- The residue check only asserted that this task's own artifacts were gone. A
  cleanup check must also assert that pre-existing directories still exist, or it
  cannot distinguish "cleaned up" from "deleted too much".
- Rules that follow: build paths with `Join-Path`; delete only paths recorded at
  creation time; never delete a parent of a known user directory; never use
  `-Force` on a directory this task did not create; put every artifact under one
  dedicated scratch root so cleanup is a single deletion of a directory this task
  created.

## A test harness must not encode the bug it is testing

- PowerShell 5.1 decodes a `.ps1` file as the ANSI code page unless it has a BOM.
  A harness script containing a non-ASCII path was silently mangled, so the
  extraction landed in a directory whose name was mojibake and the later
  `Start-Process` failed with a path that did not exist. The product was fine;
  the harness was wrong.
- `Start-Process -ArgumentList` also mangles non-ASCII arguments through the ANSI
  code page. Passing `-File <non-ASCII path>` failed while `-File start.ps1` plus
  `-WorkingDirectory <non-ASCII path>` worked, because the path never entered the
  child command line.
- Build non-ASCII test paths from codepoints inside a pure-ASCII script
  (`-join ([char]26032, ...)`) and compare codepoints rather than displayed text.
  The console code page renders `中文` as `????` and `café` as `caf‚`, so a
  visual comparison proves nothing either way.
- `[string]::Concat` has no three-argument overload; `-join` on a char array is
  the form that works.

## A validation duplicated in a wrapper script must be updated with the rule it copies

- `packaging/start.sh` and `packaging/start.ps1` repeat the Node's startup
  refusals so the message appears next to the person who can fix it. That
  duplication is deliberate, but it means one rule has two implementations and
  only the Node's was updated when `allow_filesystem_root` was added.
- The result was a feature that worked in the binary and was unreachable on the
  delivery path the operator actually uses: a bundle refused a volume root before
  the Node ever read the policy, and the generated policy never carried the key.
- When a rule gains an exception, grep the wrapper scripts for the refusal message
  rather than only the Go source. A duplicated check is a second place the rule
  lives, and it fails silently because the wrapper refuses earlier and more
  clearly than the binary would.
- The same applies to the generated artifact: a script that emits a policy from a
  simpler input format cannot express a new policy-level key until that input
  format grows a way to state it. Adding the key to the schema is half the change.

## A test that no target runs is not a test

- `tests/e2e/verify_package.sh` existed and passed when invoked by hand, but no
  Makefile target ran it. `grep -n "verify_package" Makefile` returned nothing
  while the file was 308 lines long and asserted the whole delivery path. The
  `e2e` target ran four other scripts and stopped.
- The consequence is worse than a missing test, because the file's existence
  suggests coverage. A reviewer who sees `verify_package.sh` in `tests/e2e/`
  reasonably assumes `make check` runs it, and the assertions it holds are then
  trusted without ever executing. The bundle could have stopped starting and
  `make check` would still have been green.
- The detection failure is structural: a test file is discovered by a runner, and
  a shell script is discovered by nothing. Go tests are found by `go test ./...`,
  Gherkin by the BDD tag, but a `.sh` under `tests/` is only run if a target names
  it. Adding a script is therefore half a change; wiring it into a target is the
  other half.
- Check this by listing what a target actually invokes and comparing it with what
  exists: `grep -n "tests/e2e" Makefile` against `ls tests/e2e/`. A file in the
  second list that is absent from the first is a test nobody runs.
- The same reasoning applies to the assertions themselves. The five opt-in
  assertions were written before the wiring, so for one turn the repository
  contained evidence that had never been produced by the standard suite. Running
  the script by hand proves the assertions are correct; only the wiring proves
  they keep being correct.

## A security rule that answers differently under two configurations is not a rule

- The deny list was extended to refuse a symlink alias pointing at the Node's
  config directory. The first version refused the alias under a whole-volume scope
  and reported it under a subdirectory scope, because an alias that escapes the
  scope root cannot be resolved through the `os.Root` handle, so the ancestor walk
  returned false and the code fell through to the "report the link" branch.
- The same alias, the same target, two answers, decided by an unrelated
  configuration detail. That is not a policy, it is an accident of which code path
  could resolve the path. A reviewer reading either branch alone would have
  approved it.
- The fix was to resolve the link target outside the handle for exactly the case
  the handle cannot answer. A `stat` outside the handle is not an open, so it
  answers "is this one of my own directories" without reading anything.
- Check a new refusal under both scope shapes before believing it. A rule tested
  only under the shape where the handle can resolve the path is a rule whose
  other half is untested, and the untested half is the one that leaks.

## Withholding a field is not the same as refusing the request

- The first version of the alias fix refused to report a symlink's target but
  still reported the link. The reasoning was that the link is a real directory
  entry the operator created, so hiding it hides their file.
- It leaked anyway. A symlink's reported size is the length of its target, so
  `size 14` next to `link_target` withheld answered the question the withholding
  was meant to refuse. Measured: `Lstat` on `alias -> ../node/config` reports
  `size = 14`, and `len("../node/config") == 14`.
- A partial disclosure is a disclosure. When a field is withheld because it names
  something secret, check every other field of the same record for a derived
  value: a length, a hash prefix, a count, a modification time. The derived value
  is often enough to answer the question.
- The correct answer was to refuse the request, because the deny list answers by
  identity: `config` is refused, so an alias resolving to `config` is refused too.
  Consistency with the rule beat a plausible-sounding argument about the
  operator's convenience.

## A test that measures the wrong layer passes for the wrong reason

- The alias tests were first written with **absolute** symlink targets. `os.Root`
  refuses any absolute target unconditionally, so every one of those tests was
  measuring `os.Root` rather than the deny list. They would have passed with the
  deny-list code deleted.
- Switching to **relative** targets made the tests measure the rule under test,
  and the first run then failed — which is the evidence that the earlier version
  had been proving nothing.
- The same trap appeared a second time in the same file: a subdirectory scope whose
  alias points outside the root is refused by `os.Root` before the deny list runs.
  Only the whole-volume case, where the config directory is inside the scope,
  genuinely exercises the ancestor rule.
- Before trusting a security test, ask which layer would have to be broken for it
  to fail. If the answer is "a layer below the one I changed", the test is not
  covering the change.

## A secret compiled into a binary needs a deny entry, not a better encoding

- Embedding a secret with `-ldflags -X` stores it as plain text in the data
  section. `strings` recovers it. Base64, compression and obfuscation all decode
  with the same command, and encryption needs a key the binary must also carry, so
  no encoding makes an embedded secret safe from someone holding the file.
- The threat that can be answered is the **remote** one. A scope that contains the
  binary serves it, so a caller with a valid node credential reads the secret out of
  the file. Adding the running executable to the deny list closes that path, and it
  is the only protection that changes the outcome.
- The deny entry must be conditional on the secret actually being present. A
  normal build discloses nothing by being read, and refusing it would break a
  legitimate use such as serving the install directory. The condition belongs on
  "does this build carry a secret", not on "is this build embedded": a build with
  only a Server URL and a policy carries none.
- Use `os.Executable()`, not `os.Args[0]`. The latter is whatever the launcher
  typed — a relative path, a symlink, or a bare name resolved through `PATH` — and
  a deny list that compares by file identity will not match a name that does not
  resolve to the running file.
- State the limitation where the value is defined, not only in a design document.
  A reader of the packaging script and a reader of the package comment must both
  learn that the binary is a credential.

## A second configuration source needs a stated precedence and one refusal

- Two sources for one value is a question about which wins. Answer it field by
  field and write the answer down, or the answer becomes whatever the code happened
  to do first.
- Environment over embedded is the useful order: an operator can repoint one binary
  without a rebuild, and a rebuild is the expensive path a self-contained build is
  most likely to create.
- A whole document cannot be overridden safely. An embedded policy plus a policy
  file path is two complete policies, and nothing says which is in force. Refuse the
  second source rather than merging, preferring or ignoring it: a refusal is
  visible, a silent replacement is not.
- A second entry point beats a nil-path special case when the failure modes differ.
  "The file is missing" and "the document is malformed" are different errors, and a
  single function taking an empty path has to guess which one the caller meant.
- Share the tail, not the head. Both entry points must reach the same validation and
  the same scope-opening code, so the fence cannot be configured differently
  depending on how the policy arrived.

## A new packaging branch must be tested with the inputs it will actually have

- Two defects in the new branch were invisible to reading and obvious to running:
  the output directory was never created, and a host binary was required that the
  branch never uses. Both were masked in normal use only because the Makefile target
  happened to build the host binary first.
- A packaging mode is a program with inputs, so test it with the inputs the mode
  actually needs: an empty output directory, no host binary, and a scope list that
  must be validated before the build rather than after.
- The order of operations is part of the contract. The scope list is validated
  before the binary is built because the embedded mode compiles it in; building
  first and reading the list afterwards would let the compiled policy and the
  validated list differ.
- Never resolve a path on the build host when the artifact runs elsewhere. A zip
  bundle resolves at start time on the target; an embedded policy is fixed at build
  time, so resolving would bake this host's filesystem into a binary meant for
  another machine.

## A scope directory that does not exist is tolerated, not refused

- **Superseded measurement.** An earlier version of this file recorded that a
  policy naming a missing scope path refused startup as a whole, measured with 3,
  20 and 200 missing scopes and with 50 valid scopes plus one missing one. That
  was the behaviour at the time and it is no longer the behaviour. The human
  required the opposite: a policy may name a directory that has not been created
  yet, and on Windows a drive letter may have no volume behind it, so one absent
  directory must not stop a Node that serves several.
- The current rule: an absent scope path starts the Node. The scope stays defined,
  keeps its grant, is reported at WARN with its path, appears in `absent_scopes` on
  the ready line, and answers `not_found` for `file.read`, `file.list` and
  `file.stat`. Measured on Linux with three absent scopes and on Windows with
  `E:\`, `F:\` and an absent `C:\` subdirectory; the process stayed alive in every
  case.
- A scope path that exists but is a file (`is not a directory`), a symlink root, a
  relative path, the home directory, a mount point and an existing filesystem root
  are all still startup refusals. Only absence was relaxed, and the difference
  matters: a file root makes every path inside it meaningless, while an absent
  directory has nothing inside it to serve.
- A path *inside* a valid scope that does not exist is a per-request `not_found`.
  Measured with 1500 requests: all `not_found`, the Node alive, RSS oscillating
  between 6772 and 8420 KB rather than climbing. A missing path is not a crash and
  not a leak.
- The identity file is written before the authority is loaded, so a Node that
  refuses to start because of a bad scope still leaves an `identity` file behind.
  Harmless, but it means "the Node never started" and "the Node has no identity"
  are different states.
- A tolerance that is only in the code is not a tolerance. The refusal was also
  asserted by a unit test, a BDD scenario, a test-case document, an adversarial-case
  document and an enforcement checklist, and every one of them had to be inverted
  in the same change. A document that still says "Expected: Startup fails" is read
  by the next person as the specification, and the code is then "fixed" back.

## The same missing directory answered differently depending on the operation

- `file.read` and `file.stat` on a scope whose directory was deleted underneath
  the running Node answered `not_found`; `file.list` on the same scope answered
  `internal`. `Read` and `Stat` reach the directory through `openValidated`, which
  calls `classifyOpenError`; `List` opens the directory successfully — the
  `os.Root` handle still references the deleted inode — and only fails at
  `Readdirnames`, which mapped every failure to `CodeInternal`.
- A caller that retries on `internal` and gives up on `not_found` therefore did
  the opposite of the right thing, because retrying can never succeed: the handle
  keeps the deleted inode, so a directory recreated at the same path is not
  adopted. Measured before the fix: after delete and recreate, `read` still
  returned `not_found` and `list` still returned `internal`.
- The classification belongs in one place. Two mappings for one condition is how
  the three operations drift apart, and the drift is invisible in review because
  each function reads correctly on its own. The fix added
  `classifyDirectoryReadError` immediately after `classifyOpenError`, so the two
  sit side by side and a future change to one is visible next to the other. See
  `issues/done/issue-list-reports-internal-for-a-deleted-scope-directory.md`.
- Only a missing directory becomes `not_found`. Every other failure while reading
  a directory stays `internal`, because a genuine I/O failure is a Node defect and
  not a caller-visible condition. A classifier that returned `not_found` for
  everything would tell a caller to give up on a condition a retry might fix.
- A test that asserts only `err != nil` passes both before and after the fix. The
  existing `TestListReportsAMissingDirectory` did exactly that, so it proved
  nothing about the code. Assert the code, and assert that all three operations
  agree, because agreement is the property that was broken.
- Prove the test is not vacuous by mutating the fix: reverting `List` to the
  hardcoded `internal` must fail the agreement test, and making the classifier
  always return `not_found` must fail the genuine-failure test. Both mutations were
  run and both failed as expected, then the file was restored and its md5 compared
  with the backup.
- The case is unreachable on Windows, where a directory the Node holds open cannot
  be deleted or renamed. A test for it must skip when the deletion is refused,
  rather than reporting a platform limitation as a defect in the fence.

## Windows cannot delete a directory the Node holds open

- The Linux case "delete the scope directory while the Node runs" is unreachable
  on Windows. `Remove-Item -Recurse -Force` fails with "The process cannot access
  the file because it is being used by another process", and so does
  `Rename-Item`. The `os.Root` handle holds the directory open, so the directory
  cannot be removed or renamed out from under the Node.
- `-Recurse` still deletes the *contents* before failing on the directory itself,
  so the reachable Windows state is an emptied scope rather than a deleted one.
  Measured: `file.list` on the emptied root returned success with empty output,
  and every missing path returned `not_found`. The Windows answer was already
  consistent, which is why the `internal` defect was Linux-only in practice even
  though the code path is platform-independent.
- A platform difference that makes a case unreachable is not a passing test. The
  Linux behaviour is the one a caller sees, so the defect was real; the Windows run
  proves only that Windows cannot reach it, not that the code is correct. The fix
  is therefore stated for all platforms, and the test skips on Windows instead of
  being deleted.

## A tolerance must invert every artifact that asserted the refusal

- Turning a startup refusal into a tolerance is not a one-file change. The rule
  lived in the code, in a unit test, in a BDD scenario, in a test-case document, in
  an adversarial-case document and in an enforcement checklist. Each one asserted
  the refusal, and each one had to be inverted in the same change.
- The dangerous half is the documents. A test that still asserts the old refusal
  fails loudly, but a case document that still says "Expected: Startup fails" is
  read by the next person as the specification, and the code is then "fixed" back.
  Grep the refusal message and the word "fails startup" across `docs/`, not only
  across the source.
- A test whose fixture encodes the now-legal state must be re-pointed, not deleted.
  Two tests used a missing directory to prove handle cleanup on the failure path.
  Deleting them because their setup became legal would drop the coverage the setup
  existed to provide; pointing them at a regular file keeps the property and the
  refusal.
- Mutation-test the tolerance in both directions. Restoring the refusal must fail
  the tolerance tests, and answering the wrong code must fail the code assertions.
  A tolerance test that passes with the tolerance removed is measuring nothing.
- A relaxed rule needs a stated boundary, or it becomes a hole. The filesystem-root
  rule is skipped for an absent path because a volume with no volume behind it has
  no blast radius, but the skip must be fail-closed across restarts: when the
  volume appears, the next startup refuses it. Measured on Windows with `subst E:`,
  which is the only way to create and remove a volume on demand.
- An absent path makes several other rules vacuous rather than relaxed, and the
  difference matters in review. A path that does not exist is not a symlink, is not
  a mount point and is not the home directory, because all three exist. Writing
  those as "relaxed" invites someone to relax them for a path that does exist.
- `not_found` and `denied` answer different questions. An absent scope has a grant
  and no directory, so `denied` would send the operator hunting for a policy
  problem that is not there. Keep the grant check first so the answer still does
  not disclose whether the directory exists.

## A child process started over ssh dies with the session

- `Start-Process` on Windows creates a child of the ssh session, and the child is
  killed when the session ends. The Node logged `channel established` and then the
  Server logged `connection reset by peer` seconds later, with no error on the Node
  side. The run looked successful because the evidence was captured before the
  disconnect.
- Run the long-lived process in the foreground inside a tmux-held ssh session, so
  the session stays open for as long as the process must live. A backgrounded
  process plus a captured log is not evidence that the process survives.
- Verify survival explicitly after the launching command returns: list the process
  by id and start time on the remote host, and check the Server still sees the
  channel. A log line saying `ready` proves it started, not that it is still there.
- Distinguish your own processes from pre-existing ones by start time before
  killing anything. The Windows host had two Nodes from two days earlier; a
  `Get-Process connector-node | Stop-Process` would have killed someone else's
  work.


## An orphan check that matches by name cannot tell whose process it found

- `tests/e2e/reconnect.sh` ends with `pgrep -af 'bin/connector-(server|node)'` and
  fails if anything matches. That check is correct in intent and wrong in
  reach: it matches every connector process on the host, not the two this script
  started. `make e2e` therefore failed with
  `orphan processes are still running: 2684897 ... 2684911 ...` while the script's
  own cleanup had worked perfectly.
- The two processes were 1 hour 47 minutes old, started at 19:23:49 by an earlier
  e2e run that had been interrupted. `ps -o lstart` is what showed it; `pgrep -af`
  alone shows a command line and no age, so the output reads as if the current run
  leaked them.
- The consequence is worse than a false failure. A check that fails for a reason
  outside the code under test teaches the operator to ignore it, and the next real
  leak is then ignored too. It also cost a full e2e cycle to diagnose, because the
  first hypothesis is always "the cleanup is broken".
- The fix is to compare against the PIDs the script recorded, not against a name
  pattern. `start.sh` already writes `E2E_SERVER_PID` and `E2E_NODE_PID` into
  `$ENV_FILE`, so the check can ask whether those exact PIDs are still alive. A
  name pattern can only answer "some connector process exists", which is a
  different question.
- Until that fix lands, the operational rule is: before reading an orphan failure
  as a leak, check the age of every PID it names with `ps -o pid,lstart,etime`.
  A process older than the run that reported it was not started by that run.
- This is the same root cause as the Windows lesson above, seen from the other
  side. There, a name-based kill would have destroyed someone else's work; here, a
  name-based check reported someone else's work as this run's leak. Both are
  answered by identifying a process by the PID that was recorded at creation, and
  neither is answered by its name.

## A cleanup that reports success is not a cleanup that happened

- The Windows cleanup script printed `removed cfgalias` and `removed escape`, and
  the very next listing still showed both entries. The script ran with
  `$ErrorActionPreference = "Continue"`, so `Remove-Item` failed silently and the
  `Write-Output "removed ..."` line ran anyway. The success message was written by
  the script, not by the operation.
- Re-running with `-ErrorAction Stop` produced the real errors, and both were
  PowerShell 5.1 defects rather than permission problems:
  `Remove-Item` on a directory symlink throws `System.NullReferenceException`, and
  on a directory containing a symlink it throws
  `There is a mismatch between the tag specified in the request and the tag present
  in the reparse point`.
- The second failure was protective. `Remove-Item -Recurse` follows a reparse
  point, so the `escape` directory containing `out -> C:\Windows` was one retry
  away from deleting the Windows directory. The tag mismatch stopped it. A
  cleanup script must never retry a `-Recurse` deletion of a directory it did not
  create, and must never treat a failure as "try harder".
- `cmd /c rmdir` removes the link itself and does not follow it, so it is the
  correct tool for a directory symlink on Windows. It succeeded on all three
  entries where `Remove-Item` failed twice.
- Verify a destructive cleanup by measuring what must survive, not by reading the
  script's own output. The count of `C:\Windows\System32` entries was 4099 before
  and 4099 after, which is the evidence that the link target was untouched. A
  script that only asserts its own artifacts are gone cannot distinguish "cleaned
  up" from "deleted too much".
- The general rule: a cleanup script's log line is a claim, and a claim needs a
  measurement. Print the resolved path, then re-read the directory and print what
  is actually there. If the two disagree, the script is wrong, not the listing.

## Decompress straight to the destination

- A Server binary was transferred as gzip, decompressed to `connector-server.new`,
  and then overwritten by `mv connector-server.new connector-server` after the
  decompression had already written the correct file. The result was a truncated
  5931008-byte binary where a 7626936-byte one had existed, and the container
  failed to start.
- The cause is a two-step rename around a step that already produced the final
  file. `gunzip -c x.gz > x` writes the destination directly and atomically enough
  for this purpose; adding a `.new` intermediate creates a second name that can be
  moved over the good file by mistake.
- Verify a transferred binary by size and sha256 against the build host before
  starting it. The truncated file was caught by `ls -l` showing a size that did not
  match the local artifact, which is cheaper than reading a container log.

## A launcher script is the configuration, not a convenience

- Running `connector-node.exe run` directly on the Windows host failed with
  `CONNECTOR_NODE_SERVER_URL is empty`, because `start.ps1` is what exports the
  environment variables and generates `policy.yaml` from `scopes.txt`. The binary
  has no defaults for either.
- The failure looks like a broken binary and is actually a missing launcher. When a
  bundle ships a start script, the script is part of the contract: the documented
  way to start the Node is the script, and invoking the executable directly is an
  undocumented path that is not required to work.
- Start it through WMI rather than `Start-Process`, so the process is not a child
  of the SSH session and does not die when the session closes. A log line saying
  `ready` proves it started, not that it is still there; check the PID and its
  start time afterwards.

## A container that runs as an unprivileged user needs the credential file's owner changed

- The Server container runs as `65534:65534`. A `client-credentials.yaml` created
  by root with mode `0600` is unreadable inside the container, so the Server
  refuses to start even though the file looks correctly protected from the host.
- Mode and owner are two halves of one permission. `chmod 600` on a root-owned file
  protects it from other host users and simultaneously locks out the process that
  must read it. The fix is `chown 65534:65534` plus `chmod 600`, and the reason the
  mode check exists is unchanged: the file holds secrets that never expire.
- Mount the credential file as a single file rather than mounting its directory.
  A directory mount would expose `server.env` and the rollback copies inside the
  container for no benefit.

## A proof that binds another header must be tested by substituting that header

- The client proof includes the digest of the node proof header, so a valid client
  proof cannot be reused with a different node proof. That property is invisible to
  a test that only sends correct proofs, and it is the property that stops a caller
  from keeping a client proof while swapping in a node proof for another scope.
- The test that proves it signs one path and sends another, and the Node refuses
  with `signature does not verify`. A test that only checks "a wrong secret is
  refused" measures the HMAC, not the binding.
- Reproduce the canonical signing string in a second implementation before trusting
  a hand-built proof. The Python probe returned 200 on its first call, which is the
  evidence that the canonical form was read correctly from the code rather than
  guessed; a probe that fails on its first call proves nothing about the product.

## A skill is documentation for someone who cannot read the code

- The `-o` feature was implemented, documented in `docs/API.md`, recorded in
  `features/90ai-added.md`, tested and committed — and `skills/connector-client/`
  still taught `file.read > notes.md` as the way to read a file. That example
  writes one capped response, so a user following it on a large file gets the
  first 256 KiB and a stderr notice they may have redirected away.
- The gap is structural rather than careless. `docs/API.md` is written for a
  reader who can open the source; a skill is read by someone who has only the
  binary. The two audiences need different sentences, so updating one does not
  update the other. A feature is not delivered until the skill names it, because
  the skill is the only documentation its reader will ever open.
- The detection failure is that nothing links the two. No test reads the skill, no
  checklist item asks whether the skill mentions the new flag, and the skill's own
  text was internally consistent — it described the old behaviour accurately. A
  document that is correct about a superseded interface reads as correct.
- Check by grepping the skill for the flag name after adding a flag:
  `grep -n -- '--output' skills/*/SKILL.md`. An empty result on a flag the binary
  accepts is the defect, and it is invisible in every other artifact.
- Write the observable result, not the mechanism. The Operations table said
  `file.list` returns `entries`: name, type, size, mode, modified_at — field names
  from a struct the reader cannot see. It now says "one line per entry: name, type,
  size", which is what appears on their terminal. The first version is a claim
  about code; the second is a claim about output, and only the second can be acted
  on.
- Quote the message and the status together. The skill said an existing `-o`
  destination exits `2`; the binary exits `1` while printing a message that begins
  `usage:`. Both halves were wrong in a way that only running the command revealed.
  A documented exit status is a claim like any other, so it is measured, not
  inferred from the error's type.
- The `ErrUsage` wrapper on that path was decorative: `openDestination` wrapped the
  refusal, and `Run` returns `1` for every error from `writeToDestination` without
  unwrapping it. The message prefix and the status disagreed, and a script branching
  on the status could not tell "the command line was rejected" from "the request ran
  and the write was refused". Fixed by dropping the wrapper, so the message matches
  the status; recorded in
  `issues/done/issue-output-refusal-exits-one-with-a-usage-message.md`.
- The same wrapper is still decorative in the other direction on the `Client.Send`
  path: ten local checks wrap `ErrUsage` and `Run` returns `1`, so the prefix is right
  and the status is wrong. Two defects of one shape, and fixing the first did not fix
  the second because the correct answer differs: there the status must change, here
  the message had to. Recorded as
  `issues/issue-send-time-validation-exits-one-with-a-usage-message.md`.
- A test that asserts the message and the status separately cannot see that the pair
  is inconsistent. `TestOutputRefusesAnExistingDestination` checked that the message
  contained `--force` and that the status was non-zero; each assertion passed while
  the combination was wrong. The fix was to strengthen that test to read the pair,
  not to add a second test beside it: a duplicate in another file would have left the
  weak assertion in place and made the suite look better covered than it was.
- A skill's `description` is what decides whether it is loaded at all. Adding a
  capability without adding it there means the skill is not selected for the
  request that needs it, so the feature stays undiscoverable even after the body
  documents it.

## A published port is a value in four places, not one

- Changing the Server's published port from `18444` to `8743` looked like one
  line in `docker-compose.yaml`. It is four values: the Server's compose file, the
  repo copy of that file, the zip node's `server_url` file, and the embedded
  node's compiled-in URL. Updating the first two leaves both Nodes dialling a port
  nothing listens on, and the failure appears on the Windows host as a retry loop
  rather than on the host that was edited.
- The embedded URL cannot be edited. It is stored in the binary's data section by
  `-ldflags -X`, so the artifact must be rebuilt and redeployed. Confirm the new
  value without running the binary:
  `strings bin/connector-node-windows-amd64.exe | grep -F 'ws://192.168.2.3:8743/channel'`.
- The container-internal listen address does not move. `CONNECTOR_SERVER_LISTEN`
  stays `0.0.0.0:8443` and only the host mapping changes, so the healthcheck
  (`nc -z 127.0.0.1 8443`) and the single-listener design are untouched. A change
  that also moved the internal port would break the healthcheck silently, because
  the container would still report healthy while nothing was published.
- Verify the change from the outside, not from the compose file. `docker ps`
  showing `0.0.0.0:8743->8443/tcp` proves the mapping; only a real CLI call proves
  a Node is reachable through it. The old port must also be checked, because a
  stale listener would make the new mapping look correct while the old one still
  answered: `18444` returned `rc=1, connect: connection refused`.
- The repo copy and the deployed copy had already diverged: the deployed
  `docker-compose.yaml` carries a `volumes` entry for the client credential file
  that the repo copy lacks. Editing the repo file does not deploy anything, and
  editing the deployed file does not update the repo. Compare the two before
  assuming a one-line change is complete.

## A guard that has never failed is not evidence

- Four help guards passed for many commits while asserting nothing. Each used
  `strings.Contains(page, name)`, which a *mention* satisfies: the name appears in
  prose, in an example, or in the SYNOPSIS, so deleting the documentation entry
  left the guard green. Reading the test source would not have found it, because
  each test reads correctly on its own; only mutating the help text did.
- The fix is a structural assertion, not a stronger substring. `hasEntry` requires
  a two-space-indented line beginning with the name, `hasFlagEntry` a line
  beginning with the flag, `section` one upper-case section, `exampleBlock` a
  command line recognised by content. A substring cannot tell an entry from a
  sentence about the entry.
- Every helper must fail loudly when it finds nothing. The wrong-page defect was
  caught by `t.Fatalf("... this guard is measuring nothing")`, not by the
  assertion that followed it. A helper that returns an empty string on a miss
  turns the guard into a test of the empty string.
- Mutate the artifact, not the test. Renaming `--force` to `--forceX` in the help
  text is what proved the guard works; editing the test proves only that the test
  can be edited.
- A mutation whose new value contains the old value is not a mutation.
  `REPLAY_CAPACITY` to `REPLAY_CAPACITYX` stayed green because the substring was
  still present; `QUEUE_DEPTH` failed correctly. Check that the mutation actually
  removes what the guard looks for.
- A guard that enforces one wording tests style, not the rule. Requiring the word
  `absolute` failed on entries saying "A relative path is refused", which is the
  same rule. Accept every spelling that states it, and refuse only an entry that
  states none.
- Restore from a backup and compare `md5sum` after every mutation. A mutation left
  in place is a product change nobody reviewed, and the next run would measure the
  mutated text.

## A documented rule the help omits is learned from a startup failure

- Six path variables are refused when relative, and neither help page said so. The
  operator who exported a relative `CONFIG_DIR` met the rule as
  `is relative; a relative path resolves differently per launch`, which reads as a
  bug rather than as a documented constraint.
- The gap is invisible to a completeness guard that counts variables, because the
  variable *is* documented; only the constraint on its value is missing. A guard
  for this must assert the rule inside the entry, which is why `entryFor` isolates
  one entry rather than searching the page: "absolute" appears elsewhere on the
  page in the policy description, and a whole-page search would pass on that
  unrelated sentence.
- Ask what the operator must know to make the value work, not only which values
  exist. A variable with a constraint and no stated constraint is documented in
  name only.
