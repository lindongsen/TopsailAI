---
maintainer: AI
author: DawsonLin
status: done
severity: high
created: 2026-11-13
platform: all
---

# `make check` reports success while a test suite fails

## Symptom

`make check` exits 0 and prints no error, while the BDD suite it depends on is
failing. The two commands disagree about the same code:

```
$ go test -count=1 -tags 'bdd' ./tests/bdd/...
FAIL
FAIL	topsailai_connector/tests/bdd	0.014s
$ echo $?
1

$ make bdd
... same FAIL output ...
$ echo $?
0
```

`make check` depends on `bdd`, so a green `make check` is not evidence that the
BDD suite passed.

## Impact

This is the most dangerous class of defect in a verification tool: it reports the
opposite of the truth. Every acceptance decision that cited a green `make check`
was made on a signal that cannot distinguish pass from fail.

The concrete consequence is already visible in the repository. Commit `24119e24`
changed `Authority.AuthorizeOperation` to return `unsupported_operation` for
`file.write` and `command.exec`, and updated `docs/API.md` and
`authority_test.go` to match. It did not update
`tests/bdd/features/node-authority.feature`, which still expects `denied`. The
BDD suite has been failing since that commit, and `make check` reported success
the whole time.

## Root cause

Every test target pipes its command through `tee` so the output is both shown and
saved:

```make
bdd:
	go test -count=1 -tags '$(BDD_TAGS)' ./tests/bdd/... 2>&1 | tee $(TMP_DIR)/bdd-test.log
```

The Makefile sets `SHELL := /bin/bash` but never enables `pipefail`. In a bash
pipeline the exit status is the status of the **last** command, which is `tee`.
`tee` succeeds whenever it can write the log, so the pipeline reports success
regardless of what `go test` returned.

The same pattern appears in `test-unit`, `test-server`, `test-node`,
`test-shared`, `coverage`, `integration`, `bdd` and all four `e2e` lines, so the
defect is not specific to one suite.

## Detection failure

Nothing tested the test runner. A Makefile target is not covered by `go test`, and
the failure mode is invisible in the output: the log file contains the real
`FAIL` lines, so a human reading `.tmp/bdd-test.log` would see the truth, while
the exit status and the terminal summary say success.

The `e2e` target is worse than the others: it runs four scripts as four separate
pipeline lines, so a failure in `start.sh` does not stop `run.sh` from running
against a Node that never started, and the target still exits 0.

## Fix

Enable `pipefail` for every recipe, so a pipeline fails when any stage fails:

```make
.SHELLFLAGS := -o pipefail -c
```

The leading dot is required: `.SHELLFLAGS` is the special variable Make uses to
build the shell command line, while a plain `SHELLFLAGS` is an ordinary variable
that Make silently ignores. The first attempt at this fix used the undotted name
and changed nothing, which is worth recording because the failure is silent.

Only `pipefail` is added. `-e` and `-u` would change nothing here: every recipe
line already runs in its own shell, so Make stops at the first failing line
without help, and no recipe uses a shell variable that could be unset.

The log files keep working: `tee` still writes them, and the pipeline now also
propagates the failure.

## Verified on

Linux build host, GNU Make 4.2.1. Before the fix, `go test -tags bdd
./tests/bdd/...` returned 1 and `make bdd` returned 0. After the fix, `make bdd`
returns 2 (Make's error status) for the same failing suite, and returns 0 once the
feature file is corrected.
