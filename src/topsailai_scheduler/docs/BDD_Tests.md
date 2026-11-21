---
maintainer: AI
workspace: /TopsailAI/src/topsailai_scheduler
ProjectFolder: /TopsailAI/src/topsailai_scheduler
ProjectRootFolder: /TopsailAI/src/topsailai_scheduler
ProjectCode: SCHEDULER
programming_language: go
---

# BDD Tests

The BDD suite states what the scheduler does in the operator's language and
proves it against the real binary. Nothing inside the scheduler is replaced by a
test double: a real daemon runs in a tmux session, the real CLI talks over the
real control socket, and the real provider protocol is spoken to
`providers/mock`. A passing scenario is therefore evidence about the shipped
binary rather than about a stub.

## Why the mock provider is the instrument

A scheduler can look correct while silently dropping a field. If the provider
records only the command, then a scheduler that forgets the environment
variables, the workspace or the timeout still passes every test. The mock
provider closes that gap by persisting the request document verbatim as
`<run_id>.request.json` before it runs anything, so every field the scheduler
sends can be asserted, including the fields a real provider would ignore.

This is what makes the suite a safe live test: the whole path from task file to
supervised run is exercised, and no agent is ever started.

The mock also refuses a `protocol_version` other than `1`, including a missing
one. A provider that guessed the version would silently misread a future
scheduler.

## Layout

```text
tests/bdd/
├── conftest.py                          session fixture, task holder
├── support.py                           Session harness
├── steps.py                             every Given/When/Then, defined once
├── test_<module>.py                     one binding module per feature
└── features/
    └── <module>.feature                 the scenarios
```

A binding module is nine lines: it imports the feature and the shared steps.
The scenarios live in the feature file, the harness lives in `support.py`, and
the step text lives in `steps.py`.

Steps are defined once for the whole suite rather than beside each feature.
pytest-bdd rejects a duplicate definition, and duplicating a step per feature is
how two features drift into disagreeing about what "that task is running" means.

`conftest.py` sets `pytest_plugins = ["steps"]`. This is mandatory: importing
`steps` as a plain module leaves the fixtures its decorators create in a module
namespace pytest never scans, and every scenario then fails with a missing
fixture.

## Modules

| Feature | Scenarios | What it establishes |
|---|---|---|
| `task_discovery` | 9 | A task's identity is its relative path; a missing `.md`, an unknown key, a missing schedule, an empty content file or content shorter than the configured floor makes it `invalid`; adding and removing a file takes effect without a restart |
| `task_execution` | 7 | A launch runs the task; a non-zero exit is recorded as a fact; a timeout ends the run; a running task can be stopped; a task's environment and workspace reach the run |
| `configuration` | 9 | Every optional field is sent when named and defaulted when absent; all five placeholders expand, including one embedded in a longer argument; the protocol version is the one the provider speaks; an unknown provider is refused; a task naming a missing provider is rejected at schedule time and scheduled once the provider exists |
| `locking` | 4 | A running task is not started twice; the lock spans the whole run; the record is cleared once the run is confirmed over; a finished task can be launched again |
| `reconciliation` | 5 | A run left in flight by a killed supervisor is not started twice; the record outlives the supervisor; a recorded run that already finished stops blocking; a stop is forwarded to a recorded run and refused once the run has ended |
| `cli_contract` | 8 | The status snapshot and table name the task; a launch reports the run it started; unknown task, missing id and unknown subcommand are refused; the help text names every subcommand; a launch result reads as JSON |
| `scheduling` | 4 | A task fires on its own schedule; a five-field expression is accepted; an unparseable schedule is reported and never fires; a changed schedule takes effect without a restart |
| `concurrency_and_shutdown` | 3 | A launch waits for a concurrency slot instead of being dropped; shutdown waits for a running task; a run that outlives the grace period is canceled |
| `launcher_selection` | 3 | The agent launcher leaves the invocation to the provider; an unknown launcher is refused; the command launcher sends the command the task named |

52 scenarios in total.

### What the scheduling module proves that the others cannot

Every other module drives a run through the CLI. That proves the launch path but
says nothing about the cron: a scheduler that never fired on its own would still
pass all of them. In `scheduling` nothing calls `launch`, so a request reaching
the provider is only possible because the cron fired.

### What the concurrency module proves

The concurrency limit is a slot pool, not a rejection. A launch waits for a slot
rather than failing, and waiting is only observable as a duration. The scenario
therefore times the second launch and separately asserts that the second run
reached the provider, because a wait that ended in a silent drop would satisfy
the timing alone.

## Harness design

**One daemon per scenario.** Each scenario gets its own temporary workspace,
task tree, lock files, provider state folder and tmux session, so scenarios
cannot influence each other.

**The binary must be fresh.** `tests/binary_fresh.sh` compares the binary against
every `*.go`, `go.mod` and `go.sum`. A stale binary is a failure, not a skip: a
suite run against a stale binary proves nothing about the current source, and a
skip is how that fact gets lost.

**`daemon_pid` uses an anchored pattern.** An unanchored
`pgrep -f "<binary> run"` also matches the tmux wrapper, whose command line
merely contains that string, and the wrapper appears first. Signalling the
wrapper kills the shell without forwarding, so the daemon survives and the
scenario silently tests nothing.

**`kill_daemon` uses SIGKILL.** A graceful stop clears the lock record, and the
record is exactly what a restart has to reconcile. Reconciliation scenarios need
the record to survive.

**`terminate_daemon` uses SIGTERM and returns the elapsed time.** A drain that
waits for a run is only observable as a duration.

**A restart waits for the old daemon to disappear.** `tmux kill-session` sends
SIGHUP, which the daemon does not trap, so it dies without removing its control
socket. A new daemon in the same workspace then finds a socket that still answers
and refuses to start, because starting beside a live scheduler is exactly what it
must not do. The harness waits for the old pid to go before starting the next
daemon.

**`reconfigure()` restarts the daemon.** A daemon-wide knob such as the
concurrency limit or the shutdown grace is read once at startup and cannot be
expressed in a task file.

**A cron scenario asserts growth, not a total.** The number of runs in a window
depends on timing, so the scenario records a baseline and asserts the count grew.

**`_remember()` copies the CLI result out immediately.** `session.last_output` is
overwritten by any intervening CLI call, so a step that inspects a result after
another step has run would otherwise read the wrong one.

**`env` is asserted as `null`, not as absent.** The field is present in the
request so a provider can distinguish "the task set nothing" from "the scheduler
forgot the field".

## Running

```bash
make build
python3 -m pytest tests/bdd -q --color=no
```

One module:

```bash
python3 -m pytest tests/bdd/test_scheduling.py -q --color=no
```

The suite takes about 75 seconds. It is not parallelised: each scenario owns a
tmux session and a daemon, and the timing assertions assume the machine is not
saturated by other scenarios.

## Proving the suite has teeth

A suite that has never failed is not evidence. Each new module was verified by
breaking the behaviour it claims to cover and confirming the scenario goes red:

| Mutation | Result |
|---|---|
| Remove the `0 ` prefix for five-field cron expressions | `test_a_fivefield_schedule_is_accepted` fails: the task is never given a next run |
| Make the agent launcher send a command | `test_the_agent_launcher_leaves_the_invocation_to_the_provider` fails: `assert '/bin/true' == ''` |
| Make a launch drop instead of waiting for a slot | `test_a_launch_waits_for_a_concurrency_slot` fails: the second launch returned in 0.00s |

Each mutation was reverted and `git diff src/` confirmed empty before the suite
was run again.

## What is not covered

- **The scheduler-provider-topsailai provider against a real agent.** It is tested against a stub
  only. A manual `launch work --wait` is the remaining check.
- **Log rotation under sustained volume.** Rotation is unit tested; the BDD suite
  does not run long enough to roll a file.
- **The grace-expiry path has no exit-code assertion.** The daemon is terminated
  and the run is asserted canceled, but the exit status is not read, because the
  scenario is about the run rather than about the daemon's own exit.
