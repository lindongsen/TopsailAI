package main

import (
	"flag"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"text/tabwriter"

	"topsailai_scheduler/config"
	"topsailai_scheduler/task"
)

// checkResult is one task as reported by the check command.
//
// A valid task and a rejected file are both reported, because a checker that
// only prints problems cannot be distinguished from a checker that found none.
type checkResult struct {
	// ID is the task id, or the file path when the id cannot be derived.
	ID string `json:"id"`
	// Path is the YAML file that was examined.
	Path string `json:"path"`
	// Valid reports whether the task loaded.
	Valid bool `json:"valid"`
	// Enabled reports whether the task would be scheduled. It is a pointer so a
	// rejected task omits the field: reporting false would read as "this task is
	// disabled", which is a different statement from "this task could not be
	// read".
	Enabled *bool `json:"enabled,omitempty"`
	// Schedule is the cron expression as written in the file.
	Schedule string `json:"schedule,omitempty"`
	// Error is the reason a task was rejected, empty when it loaded.
	Error string `json:"error,omitempty"`
}

// checkReport is the whole result of one check run.
type checkReport struct {
	// TasksRoot is the absolute folder that was scanned.
	TasksRoot string `json:"tasks_root"`
	// TasksRootExists reports whether the folder was present. A missing folder
	// is not an error, but it is reported so a mistyped path is visible.
	TasksRootExists bool `json:"tasks_root_exists"`
	// Tasks holds one entry per task file, sorted by id.
	Tasks []checkResult `json:"tasks"`
	// Valid and Invalid are the counts, so a caller does not have to recount.
	Valid   int `json:"valid"`
	Invalid int `json:"invalid"`
}

// runCheck validates the task tree without contacting a daemon.
//
// The command exists because the only other way to learn that a task file is
// broken is to start the daemon and read its status or log. A checker that needs
// the very service it is meant to validate cannot be used in a pre-commit hook
// or a CI step, which is where a broken task file should be caught.
func runCheck(args []string) int {
	flags := flag.NewFlagSet("check", flag.ContinueOnError)
	flags.SetOutput(os.Stderr)
	tasksRoot := flags.String("tasks-root", "", "tasks folder, overrides "+config.EnvTasksRoot)
	asJSON := flags.Bool("json", false, "print the result as JSON")
	if _, err := parseFlags(flags, args); err != nil {
		return exitUsage
	}
	if flags.NArg() > 0 {
		return usageError("check takes no arguments, got %q", flags.Args())
	}

	cfg, err := config.Load()
	if err != nil {
		return fail("invalid configuration: %v", err)
	}
	cfg, err = applyTasksRootOverride(cfg, *tasksRoot)
	if err != nil {
		return fail("invalid configuration: %v", err)
	}

	root, err := cfg.AbsoluteTasksRoot()
	if err != nil {
		return fail("%v", err)
	}

	report, err := buildCheckReport(root, cfg.MinContentRunes)
	if err != nil {
		return fail("%v", err)
	}

	if *asJSON {
		if code := printJSON(report); code != exitOK {
			return code
		}
	} else {
		printCheckReport(report)
	}

	// A non-zero exit is what makes the command usable in a pipeline: a caller
	// must not have to parse the output to learn whether anything is broken.
	if report.Invalid > 0 {
		return exitFailure
	}
	return exitOK
}

// buildCheckReport loads the task tree and turns the result into a report.
//
// It reuses task.Load, the same function the daemon uses, so the checker and the
// daemon cannot disagree about whether a task is valid. A separate validation
// path here would drift from the daemon and make the checker untrustworthy.
func buildCheckReport(root string, minRunes int) (checkReport, error) {
	report := checkReport{TasksRoot: root, Tasks: []checkResult{}}

	if info, err := os.Stat(root); err == nil && info.IsDir() {
		report.TasksRootExists = true
	}

	loaded, failures, err := task.Load(root, minRunes)
	if err != nil {
		return checkReport{}, fmt.Errorf("load tasks from %s: %w", root, err)
	}

	for _, item := range loaded {
		enabled := item.Spec.IsEnabled()
		report.Tasks = append(report.Tasks, checkResult{
			ID:       item.ID,
			Path:     item.YAMLPath,
			Valid:    true,
			Enabled:  &enabled,
			Schedule: item.Spec.Schedule,
		})
		report.Valid++
	}

	for _, failure := range failures {
		id, idErr := task.IDFor(root, failure.Path)
		if idErr != nil {
			// A file outside the root cannot have a task id. Reporting the path
			// keeps the entry identifiable instead of dropping it.
			id = failure.Path
		}
		report.Tasks = append(report.Tasks, checkResult{
			ID:    id,
			Path:  failure.Path,
			Valid: false,
			Error: failure.Err.Error(),
		})
		report.Invalid++
	}

	sort.Slice(report.Tasks, func(i, j int) bool { return report.Tasks[i].ID < report.Tasks[j].ID })
	return report, nil
}

// printCheckReport renders the report as an aligned table.
func printCheckReport(report checkReport) {
	fmt.Printf("tasks root: %s\n", report.TasksRoot)
	if !report.TasksRootExists {
		// A missing folder is a valid empty scheduler, but it is also what a
		// mistyped path looks like, so it is stated rather than left implicit.
		fmt.Println("note: the tasks root does not exist, so there is nothing to check")
	}
	if len(report.Tasks) == 0 {
		fmt.Println("no tasks found")
		return
	}

	writer := tabwriter.NewWriter(os.Stdout, 0, 0, 2, ' ', 0)
	fmt.Fprintln(writer, "TASK\tRESULT\tSCHEDULE\tPATH")
	for _, result := range report.Tasks {
		outcome := "ok"
		if !result.Valid {
			outcome = "invalid"
		} else if result.Enabled != nil && !*result.Enabled {
			outcome = "ok (disabled)"
		}
		schedule := result.Schedule
		if schedule == "" {
			schedule = "-"
		}
		path := result.Path
		if relative, err := filepath.Rel(report.TasksRoot, result.Path); err == nil {
			path = relative
		}
		fmt.Fprintf(writer, "%s\t%s\t%s\t%s\n", result.ID, outcome, schedule, path)
		if result.Error != "" {
			fmt.Fprintf(writer, "  error: %s\n", result.Error)
		}
	}
	if err := writer.Flush(); err != nil {
		fmt.Fprintf(os.Stderr, "write check table: %v\n", err)
	}

	fmt.Printf("%d valid, %d invalid\n", report.Valid, report.Invalid)
}
