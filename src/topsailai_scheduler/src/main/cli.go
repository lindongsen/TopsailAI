package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"text/tabwriter"
	"time"

	"topsailai_scheduler/config"
	"topsailai_scheduler/control"
	"topsailai_scheduler/runtime"
)

// newClient builds a control client from the configuration.
//
// The socket path comes from the same configuration the daemon uses, so the CLI
// reaches the daemon of the project it is run in without an extra argument.
func newClient() (*control.Client, error) {
	cfg, err := config.Load()
	if err != nil {
		return nil, fmt.Errorf("invalid configuration: %w", err)
	}
	socketPath, err := cfg.AbsoluteControlSocket()
	if err != nil {
		return nil, fmt.Errorf("resolve control socket: %w", err)
	}
	return control.NewClient(socketPath), nil
}

// runStatus reports the state of every task.
func runStatus(args []string) int {
	flags := flag.NewFlagSet("status", flag.ContinueOnError)
	flags.SetOutput(os.Stderr)
	asJSON := flags.Bool("json", false, "print the raw JSON snapshot")
	if _, err := parseFlags(flags, args); err != nil {
		return exitUsage
	}
	if flags.NArg() > 0 {
		return usageError("status takes no arguments, got %q", flags.Args())
	}

	client, err := newClient()
	if err != nil {
		return fail("%v", err)
	}
	snapshot, err := client.Status()
	if err != nil {
		return fail("%v", err)
	}

	if *asJSON {
		return printJSON(snapshot)
	}
	printSnapshot(snapshot)
	return exitOK
}

// runLaunch starts one run of a task now.
func runLaunch(args []string) int {
	flags := flag.NewFlagSet("launch", flag.ContinueOnError)
	flags.SetOutput(os.Stderr)
	wait := flags.Bool("wait", false, "wait for the run to finish")
	asJSON := flags.Bool("json", false, "print the raw JSON result")
	if _, err := parseFlags(flags, args); err != nil {
		return exitUsage
	}
	if flags.NArg() != 1 {
		return usageError("launch takes exactly one task id, got %q", flags.Args())
	}

	client, err := newClient()
	if err != nil {
		return fail("%v", err)
	}
	// A waiting launch may legitimately run as long as the task's own timeout,
	// so the request bound is widened instead of cutting the run short.
	if *wait {
		client = client.WithTimeout(24 * time.Hour)
	}

	result, err := client.Launch(runtime.LaunchRequest{TaskID: flags.Arg(0), Wait: *wait})
	if err != nil {
		return fail("%v", err)
	}

	if *asJSON {
		return printJSON(result)
	}
	if result.Skipped {
		fmt.Printf("task %s is already running, no new run started\n", result.TaskID)
		return exitOK
	}
	fmt.Printf("task %s started, pid %d, trace %s\n", result.TaskID, result.PID, result.TraceID)
	if result.Record != nil {
		printRecord(*result.Record)
		if result.Record.ExitCode != 0 {
			return exitFailure
		}
	}
	return exitOK
}

// runStop stops a running task.
func runStop(args []string) int {
	flags := flag.NewFlagSet("stop", flag.ContinueOnError)
	flags.SetOutput(os.Stderr)
	force := flags.Bool("force", false, "ask the provider for an immediate stop")
	asJSON := flags.Bool("json", false, "print the raw JSON result")
	if _, err := parseFlags(flags, args); err != nil {
		return exitUsage
	}
	if flags.NArg() != 1 {
		return usageError("stop takes exactly one task id, got %q", flags.Args())
	}

	client, err := newClient()
	if err != nil {
		return fail("%v", err)
	}
	result, err := client.Stop(runtime.StopRequest{TaskID: flags.Arg(0), Force: *force})
	if err != nil {
		return fail("%v", err)
	}

	if *asJSON {
		return printJSON(result)
	}
	// The scheduler asks the provider to stop the run; it does not send the
	// signal itself, so the message must not name one.
	if result.BestEffort {
		// The run belongs to a previous supervisor, so the scheduler can only
		// forward the request. Saying "stop requested" alone would imply the
		// scheduler is watching the outcome, which it is not.
		fmt.Printf("task %s stop forwarded to the provider, pid %d (best effort: the run is not supervised, so the stop cannot be confirmed)\n", result.TaskID, result.PID)
		return exitOK
	}
	fmt.Printf("task %s stop requested, pid %d\n", result.TaskID, result.PID)
	return exitOK
}

// printJSON writes a value as indented JSON.
func printJSON(value any) int {
	encoded, err := json.MarshalIndent(value, "", "  ")
	if err != nil {
		return fail("encode result: %v", err)
	}
	fmt.Println(string(encoded))
	return exitOK
}

// printSnapshot renders the snapshot as an aligned table.
func printSnapshot(snapshot runtime.Snapshot) {
	fmt.Printf("tasks root: %s\n", snapshot.TasksRoot)
	if len(snapshot.Tasks) == 0 {
		fmt.Println("no tasks found")
		return
	}

	writer := tabwriter.NewWriter(os.Stdout, 0, 0, 2, ' ', 0)
	fmt.Fprintln(writer, "TASK\tSTATE\tSCHEDULE\tNEXT RUN\tLAST EXIT\tPID")
	for _, status := range snapshot.Tasks {
		nextRun := "-"
		if !status.NextRun.IsZero() {
			nextRun = status.NextRun.Format(time.RFC3339)
		}
		lastExit := "-"
		if status.LastRun != nil {
			lastExit = fmt.Sprintf("%d", status.LastRun.ExitCode)
		}
		pid := "-"
		if status.Run != nil && status.Run.PID > 0 {
			pid = fmt.Sprintf("%d", status.Run.PID)
		}
		schedule := status.Schedule
		if schedule == "" {
			schedule = "-"
		}
		fmt.Fprintf(writer, "%s\t%s\t%s\t%s\t%s\t%s\n",
			status.ID, status.State, schedule, nextRun, lastExit, pid)
		if status.Error != "" {
			fmt.Fprintf(writer, "  error: %s\n", status.Error)
		}
	}
	if err := writer.Flush(); err != nil {
		fmt.Fprintf(os.Stderr, "write status table: %v\n", err)
	}
}

// printRecord renders one completed run.
func printRecord(record runtime.RunRecord) {
	fmt.Printf("  exit code: %d\n", record.ExitCode)
	fmt.Printf("  duration:  %s\n", record.FinishedAt.Sub(record.StartedAt).Round(time.Millisecond))
	if record.TimedOut {
		fmt.Println("  timed out: yes")
	}
	if record.Stopped {
		fmt.Println("  stopped:   yes")
	}
}
