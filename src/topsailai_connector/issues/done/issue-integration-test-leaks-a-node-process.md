---
maintainer: AI
author: DawsonLin
status: fixed
created: 2026-11-14
resolved: 2026-11-14
---

# An integration test leaks a Node process that outlives the test run

## Symptom

A `connector-node` process from an integration run on 2026-11-10 was still
running four days later. Its binary had been deleted and its temporary directory
was gone, so it could never be restarted and nothing could ever clean it up.

```
PID 888270  PPID 1296094 (/pause)  started Tue Nov 10 17:03:39 2026
  exe=/tmp/connector-integration-3957164288/connector-node (deleted)
  cwd=/TopsailAI/src/topsailai_connector/tests/integration
  state=Sl  cpu=0.0%  listening=none  fds=6
```

It survived 362,644 seconds (4.2 days) and held no socket, so it was invisible to
any check that looks for a listening port.

## Reproduction

The leaking test is identified from the process environment, which still held the
per-test config directory:

```
CONNECTOR_NODE_CONFIG_DIR=/tmp/TestNodeRejectsAnUnknownSubcommand1288134790/001/config
```

That names `TestNodeRejectsAnUnknownSubcommand` at
`tests/integration/node_process_test.go:327`.

The test itself is correct in intent:

```go
text, err := runOnce(t, env.vars(), "serve")
if err == nil {
    t.Fatalf("process exited 0 for an unknown subcommand; output:\n%s", text)
}
```

It expects a non-zero exit. The leak happens when that expectation stops holding,
which is exactly what happened on 2026-11-10.

## Root cause

Two defects combine. Either one alone would not leak a process.

### Defect one: `runOnce` has no deadline

`tests/integration/node_process_test.go:121-127`:

```go
func runOnce(t *testing.T, environment []string, arguments ...string) (string, error) {
	t.Helper()
	command := exec.Command(nodeBinary, arguments...)
	command.Env = append(baseEnvironment(), environment...)
	output, err := command.CombinedOutput()
	return string(output), err
}
```

`exec.Command` takes no context, and `CombinedOutput` waits for the child to exit
with no bound. If the child does not exit, `runOnce` never returns.

The same file already has a `stop` helper at `:168-177` that sends SIGTERM and
waits, and its comment says "so a test never leaves a child process behind". But
`runOnce` does not use it, and `stop` cannot help a call that is blocked inside
`CombinedOutput`.

### Defect two: the binary used to accept `serve`

On 2026-11-10 the dispatch treated any unrecognised leading word as the default
subcommand. The pre-fix `splitCommand` (`git show e128c64e^`) was:

```go
switch arguments[0] {
case "run", "id", "regenerate":
    return arguments[0], arguments[1:]
}
return "", arguments
```

So `serve` became `command=""` with `rest=["serve"]`, and `command=""` dispatches
to `runNode`. Reproduced with the pre-fix function:

```
splitCommand("serve") -> command="" rest=[serve]
flag.Parse([serve]) -> err=<nil>  NArg=1  Args=[serve]
=> dispatch takes the "" branch and starts the node, ignoring [serve]
```

`flag.Parse` does not reject a positional argument, and `runNodeWithSignals` never
checks `flags.Args()`. So the Node started serving instead of failing, and
`CombinedOutput` blocked forever.

### Why the process survived the test run

`go test`'s own timeout does not kill the child. Measured with a probe that
mirrors `runOnce` exactly (`exec.Command("sleep", "300")` plus `CombinedOutput`):

```
$ go test -count=1 -timeout 3s -v ./...
panic: test timed out after 3s
...
FAIL	leakprobe	3.005s

$ ps -eo pid,ppid,etime,args | grep 'sleep 300'
1396446       1       00:03 sleep 300
```

The test binary panicked and exited, the child was **reparented to PID 1**, and it
kept running. `go test -timeout` bounds the test, not the process tree.

`TestMain` (`:24-43`) removes the temporary directory after `m.Run()`, which is why
the binary shows as `(deleted)`: the cleanup ran, the process did not.

## Timeline

| Time (2026-11-10) | Event |
|---|---|
| 17:03:39 | The orphan starts, running `serve` against the pre-fix binary |
| 17:09:56 | `e128c64e fix: report an unknown subcommand instead of starting the node` |
| 17:10:08 | `89cf6729 test: add coverage integration and bdd targets` adds the test |

The orphan was created six minutes **before** the dispatch fix landed, and the
test that now covers the fix was added twelve seconds after it. So the leak is a
one-time artifact of the window between the two commits, not a defect the test
introduced.

That does not make it harmless. The leak mechanism is still present: any future
case where the binary does not exit leaves a permanent orphan, and the test that
would catch it is the same test that hangs.

## Why it was not caught

- The test asserts on the exit status. A child that never exits produces no exit
  status, so the assertion never runs.
- `go test -timeout` reports a panic, which reads as "the test was slow", not "a
  process escaped". The panic message does not mention the child.
- The orphan held no listening socket, so a port check does not find it.
- Its binary was deleted by `TestMain`, so a check for "a connector-node binary
  exists" does not find it either.
- Nothing asserts that the process tree is empty after the suite. `make check`
  passes with the orphan running.

## Proposed fix

Bound the child and make cleanup unconditional:

```go
func runOnce(t *testing.T, environment []string, arguments ...string) (string, error) {
	t.Helper()
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	t.Cleanup(cancel)
	command := exec.CommandContext(ctx, nodeBinary, arguments...)
	command.Env = append(baseEnvironment(), environment...)
	output, err := command.CombinedOutput()
	return string(output), err
}
```

`CommandContext` kills the child when the deadline passes, so a hung child becomes
a test failure instead of an orphan. `t.Cleanup(cancel)` releases the timer even
when the child exits early.

Two further changes are worth making, and each needs its own decision:

1. **Reject a leftover positional argument.** `runNodeWithSignals` never checks
   `flags.Args()`, so `connector-node run serve` still starts the Node silently.
   Measured on the current build: it logs `connector-node ready` and dials. A
   subcommand that is not recognised should fail even when it follows `run`.
2. **Assert the process tree is empty after the suite.** A `TestMain` check that
   no child of the test binary survives would catch this class of leak directly,
   rather than relying on each helper to be correct.

## Prevention

- A helper that runs a child process must have a deadline. "The child always
  exits" is an assumption, and the test that verifies the child exits is the one
  that hangs when the assumption fails.
- `go test -timeout` is not a process cleanup mechanism. It bounds the test
  binary, and children are reparented to PID 1.
- A test that expects a failure must bound the call, because the failure case is
  exactly the case where the child may not exit.

## Resolution

Both defects were fixed, and the fix was proven by mutation rather than by a
passing suite.

### Changes

| File | Change |
|---|---|
| `tests/integration/node_process_test.go` | `context` import, `runOnceTimeout = 30s`, `runOnce` bounded by `exec.CommandContext`, new `TestNodeRejectsAnArgumentAfterRun`, `defer stop(t, first)` in `TestNodeDoesNotPrintThePairOnASecondStart` |
| `cmd/connector-node/main.go` | `rejectStrayArguments` helper, applied in `run`, `id` and `regenerate` |

`runOnce` now fails explicitly when the deadline expires, so a hung child is a
diagnosable failure instead of a permanent orphan:

```go
ctx, cancel := context.WithTimeout(context.Background(), runOnceTimeout)
t.Cleanup(cancel)

command := exec.CommandContext(ctx, nodeBinary, arguments...)
output, err := command.CombinedOutput()
if ctx.Err() != nil {
    t.Fatalf("connector-node %v did not exit within %s; output:\n%s",
        arguments, runOnceTimeout, output)
}
```

### Mutation evidence

The two fixes are independent, and the mutation that removes the argument guard
is the one that exercises the deadline.

| Mutation | Result | Orphan afterwards |
|---|---|---|
| Remove the guard from `runNodeWithSignals`, keep the bounded `runOnce` | `--- FAIL: TestNodeRejectsAnArgumentAfterRun (30.01s)`, message `connector-node [run serve] did not exit within 30s`, log shows the Node retrying `dial wss://server.example:8443/channel` | **none** |
| Guard in place, unbounded `runOnce` | does not hang, because the child exits on its own | none |

The first row is the decisive one: the same child that leaked for four days now
fails the test in 30 seconds and leaves nothing behind.

### Verification

| Check | Result |
|---|---|
| `gofmt -l cmd/ tests/` | clean |
| `go vet ./cmd/... ./tests/...` | clean |
| `run serve` | `unexpected argument "serve"; want flags only`, exit 1 |
| `serve` alone | `unknown command "serve"; want run, id or regenerate` |
| `id bogus` | `unexpected argument "bogus"; want flags only` |
| `regenerate bogus` | `unexpected argument "bogus"; want flags only` |
| `id` | prints a valid pair, exit 0 |
| `regenerate --keep-id` | same `node-id`, new token, exit 0 |
| Integration suite | 20/20 PASS, no orphan afterwards |
| `make check` | RC=0, zero FAIL, Windows cross-compile included |

### A second leak found while verifying

Verifying the fix exposed a second, independent leak in the same file.
`TestNodeDoesNotPrintThePairOnASecondStart` called `stop(t, first)` directly
rather than through `defer`:

```go
first, firstOutput := start(t, env.vars(), "run")
waitForOutput(t, firstOutput, "connector-node ready", 20*time.Second)
stop(t, first)          // unreachable if waitForOutput calls t.Fatalf
```

`waitForOutput` calls `t.Fatalf` when the marker never appears, so `stop` was
skipped and the child was left running. Reproduced by changing the marker to one
that never appears: the test failed in 2.01s and the child was reparented to PID 1.

The leak was real but self-limiting, and the reason matters. The child writes to a
pipe whose read end the test binary owns, so when the test binary exits the child
receives `SIGPIPE` on its next write and dies. Measured with a probe that closes
the read end after three seconds: the child exited with `rc=-13` (`SIGPIPE`)
within three seconds. That is why it never produced a four-day orphan, and it is
also why "no orphan after the run" would not have proven the code correct.

The fix is one word, `defer stop(t, first)`, but it changes semantics: `first` now
runs concurrently with `second` instead of being stopped before `second` starts.
The test was therefore re-verified rather than assumed still valid.

| Check | Result |
|---|---|
| Three consecutive runs | PASS each time |
| Mutation: print the pair on every start | `--- FAIL`, `second start printed the pair again` |
| Full integration suite | 20/20 PASS, no orphan |

The mutation row is the one that matters: the test still catches the regression it
was written for, so `defer` did not weaken it.

### Remaining

Two items remain open. Neither is reachable today, and neither belongs to the
defect this issue records.

#### `stop()` waits without a deadline

`stop` sends `SIGTERM`, then calls `command.Wait()` with no bound. A child that
ignores `SIGTERM` would block the test forever. Measured today, the Node exits
3 ms after `SIGTERM`, so this is latent rather than reachable. It is recorded
because the same reasoning that made `runOnce` need a deadline applies here.

#### The `topsailai_agent_cluster` leaks

The 14 leaked servers found during the orphan sweep belong to that project's BDD
harness, not to this one. Per the cross-project rule they must be reported there
rather than fixed here.
