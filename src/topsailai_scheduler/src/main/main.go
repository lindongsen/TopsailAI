// Command scheduler runs scheduled tasks discovered from a folder tree and
// exposes the standardized control contract to a CLI.
//
// Subcommands:
//
//	run      start the scheduler daemon and its control socket
//	status   report the state of every task
//	check    validate the task tree without a running daemon
//	launch   start one run of a task now
//	stop     actively stop a running task
//
// The CLI never imports the daemon: status, launch and stop talk to the running
// daemon through the control socket, so the same contract serves any future
// transport. check is the exception by design: it validates the task files
// directly, because a checker that needs the service it validates cannot run in
// a pre-commit hook or a CI step.
package main

import (
	"flag"
	"fmt"
	"os"
	"strings"
)

// Exit codes. They are stable so a script can branch on the outcome.
const (
	// exitOK means the command succeeded.
	exitOK = 0
	// exitFailure means the command failed.
	exitFailure = 1
	// exitUsage means the command line was wrong.
	exitUsage = 2
)

// usage is printed when the command line cannot be understood.
const usage = `scheduler - run scheduled tasks from a folder tree

Usage:
  scheduler run [--tasks-root <dir>]
                                start the scheduler daemon
  scheduler status [--json]     report the state of every task
  scheduler check [--tasks-root <dir>] [--json] [<task>]
                                validate the task tree, or one task, without a daemon
  scheduler launch <task> [--wait] [--json]
                                start one run of a task now
  scheduler stop <task> [--force] [--json]
                                stop a running task

A task is three files sharing one stem inside the tasks folder:

  tasks/data/work.yaml   configuration: when to run, how to run
  tasks/data/work.md     task content
  tasks/data/work.lock   runtime lock, created on demand

The task id is the YAML path relative to the tasks folder without extension,
so tasks/data/work.yaml is the task "data/work".

Environment:
  SCHEDULER_TASKS_ROOT          tasks folder, default "tasks"
                                (--tasks-root on "run" takes precedence)
  SCHEDULER_CONTROL_SOCKET      control socket, default
                                "$HOME/.topsailai/scheduler.sock"
  SCHEDULER_LOG_LEVEL           debug, info, warn or error
  SCHEDULER_LOG_OUTPUT          stdout, stderr or a file path
  SCHEDULER_MAX_CONCURRENT      runs allowed at the same time
  SCHEDULER_DEFAULT_TIMEOUT     default run timeout, for example 30m
  SCHEDULER_RESCAN_INTERVAL     how often the tasks folder is rescanned
  SCHEDULER_SHUTDOWN_GRACE      how long running tasks may finish on shutdown
  SCHEDULER_DEFAULT_PROVIDER_PATH provider executable for a task that names none,
                                required by "run", for example ./providers/mock/bin/mock
  SCHEDULER_POLL_INTERVAL       how often a running task is polled, default 5s
  SCHEDULER_PROVIDER_CALL_TIMEOUT  per-call provider timeout, default 180s
  SCHEDULER_WORKSPACE           default workspace
  SCHEDULER_MIN_TASK_CONTENT_RUNES  shortest task content accepted, default 30
`

// main dispatches the subcommand and exits with a stable code.
func main() {
	os.Exit(run(os.Args[1:]))
}

// run executes one subcommand and returns its exit code.
//
// It is separate from main so the dispatch is testable without exiting the
// process.
func run(args []string) int {
	if len(args) == 0 {
		fmt.Fprint(os.Stderr, usage)
		return exitUsage
	}

	switch args[0] {
	case "run":
		return runDaemon(args[1:])
	case "status":
		return runStatus(args[1:])
	case "check":
		return runCheck(args[1:])
	case "launch":
		return runLaunch(args[1:])
	case "stop":
		return runStop(args[1:])
	case "help", "-h", "--help":
		fmt.Fprint(os.Stdout, usage)
		return exitOK
	default:
		fmt.Fprintf(os.Stderr, "unknown command %q\n\n%s", args[0], usage)
		return exitUsage
	}
}

// fail prints an error and returns the failure exit code.
func fail(format string, args ...any) int {
	fmt.Fprintf(os.Stderr, format+"\n", args...)
	return exitFailure
}

// usageError prints a command-line error and returns the usage exit code.
//
// A wrong command line is reported separately from a failed operation, so a
// script can tell "I called it wrong" from "the task failed".
func usageError(format string, args ...any) int {
	fmt.Fprintf(os.Stderr, format+"\n", args...)
	return exitUsage
}

// parseFlags parses flags that may appear before or after a positional
// argument.
//
// The standard flag package stops at the first non-flag argument, so
// "launch demo/hello --wait" would treat --wait as a second task id. Reordering
// the arguments keeps the natural command line working without a custom parser.
//
// A flag that takes a value keeps that value attached while reordering. Without
// that, "check --tasks-root dir --json" would move --json next to --tasks-root,
// the value would be read as the flag name, and a valid command line would turn
// into a usage error.
func parseFlags(flags *flag.FlagSet, args []string) ([]string, error) {
	ordered := make([]string, 0, len(args))
	positional := make([]string, 0, len(args))
	for index := 0; index < len(args); index++ {
		argument := args[index]
		if !strings.HasPrefix(argument, "-") || argument == "-" {
			positional = append(positional, argument)
			continue
		}
		ordered = append(ordered, argument)
		if takesSeparateValue(flags, argument) && index+1 < len(args) {
			index++
			ordered = append(ordered, args[index])
		}
	}
	if err := flags.Parse(append(ordered, positional...)); err != nil {
		return nil, err
	}
	return flags.Args(), nil
}

// takesSeparateValue reports whether argument is a flag whose value is the next
// command-line word.
//
// A flag written as "--name=value" carries its own value, and a boolean flag
// never consumes the next word. An unknown flag is treated as boolean so the
// flag package reports it rather than this helper swallowing the argument that
// follows it.
func takesSeparateValue(flags *flag.FlagSet, argument string) bool {
	if strings.Contains(argument, "=") {
		return false
	}
	defined := flags.Lookup(strings.TrimLeft(argument, "-"))
	if defined == nil {
		return false
	}
	boolean, isBoolean := defined.Value.(interface{ IsBoolFlag() bool })
	return !isBoolean || !boolean.IsBoolFlag()
}
