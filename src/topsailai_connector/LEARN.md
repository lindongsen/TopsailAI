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
- The identity pair is generated at packaging time by running the Node's own `id`
  command, not by a second implementation in the packaging script. A second
  implementation is a second definition of the pair format, and the two will
  eventually disagree about what a valid pair is.
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
