// Package runtime defines the standardized contract for controlling task runs.
//
// Three operations form the contract, and each has a seam so the scheduler can
// be driven by a CLI, an HTTP handler, or a test without changing the daemon:
//
//	Launch   start one run of a task now
//	Status   report the current state of every task and run
//	Stop     actively stop a running task
//
// The daemon implements Controller. A transport such as the control socket in
// package control only translates a request into these calls, so a new
// transport never reimplements scheduling logic.
package runtime

import (
	"errors"
	"time"
)

// Errors returned by the contract. They are sentinel values so a transport can
// map them to a status code without matching on message text.
var (
	// ErrTaskNotFound means no task with the requested id is known.
	ErrTaskNotFound = errors.New("task not found")
	// ErrTaskNotRunning means the task has no in-flight run to stop.
	ErrTaskNotRunning = errors.New("task is not running")
	// ErrTaskDisabled means the task exists but is disabled in its YAML.
	ErrTaskDisabled = errors.New("task is disabled")
	// ErrShuttingDown means the scheduler is stopping and accepts no new run.
	ErrShuttingDown = errors.New("scheduler is shutting down")
)

// State is the lifecycle state of one task.
type State string

// Task states reported by Status.
const (
	// StateIdle means the task is scheduled and has no in-flight run.
	StateIdle State = "idle"
	// StateRunning means the task has an in-flight run.
	StateRunning State = "running"
	// StateDisabled means the task is present but disabled in its YAML.
	StateDisabled State = "disabled"
	// StateInvalid means the task files exist but cannot be loaded.
	StateInvalid State = "invalid"
)

// RunInfo describes one in-flight run.
type RunInfo struct {
	// PID is the process id of the run's process group leader.
	PID int `json:"pid"`
	// StartedAt is when the run started.
	StartedAt time.Time `json:"started_at"`
	// TraceID correlates the run's log entries.
	TraceID string `json:"trace_id"`
	// Launcher is the launcher name used for the run.
	Launcher string `json:"launcher"`
	// Provider is the provider name used for the run.
	Provider string `json:"provider"`
	// RunID is the provider-defined run identity, empty until the provider
	// reports it.
	RunID string `json:"run_id"`
	// Command is the executable the task asked to run, empty when the provider
	// chose the invocation itself.
	Command string `json:"command"`
}

// TaskStatus is the reported state of one task.
type TaskStatus struct {
	// ID is the task id, for example "data/work".
	ID string `json:"id"`
	// State is the lifecycle state.
	State State `json:"state"`
	// Schedule is the cron expression from the task YAML.
	Schedule string `json:"schedule"`
	// Launcher is the launcher name from the task YAML.
	Launcher string `json:"launcher"`
	// Provider is the provider name the task selects.
	Provider string `json:"provider"`
	// YAMLPath is the absolute configuration path.
	YAMLPath string `json:"yaml_path"`
	// MarkdownPath is the absolute task content path.
	MarkdownPath string `json:"markdown_path"`
	// NextRun is the next scheduled time, zero when not scheduled.
	NextRun time.Time `json:"next_run"`
	// LastRun is the most recent completed run, nil when never run.
	LastRun *RunRecord `json:"last_run"`
	// Run is the in-flight run, nil when idle.
	Run *RunInfo `json:"run"`
	// Error is the load error for an invalid task.
	Error string `json:"error"`
}

// RunRecord is the outcome of one completed run.
type RunRecord struct {
	// StartedAt is when the run started.
	StartedAt time.Time `json:"started_at"`
	// FinishedAt is when the run ended.
	FinishedAt time.Time `json:"finished_at"`
	// ExitCode is the run's exit status when the provider reported one. It is a
	// lifecycle fact, not a verdict.
	ExitCode int `json:"exit_code"`
	// TimedOut is true when the run exceeded its timeout.
	TimedOut bool `json:"timed_out"`
	// Stopped is true when the run was stopped through the contract.
	Stopped bool `json:"stopped"`
	// TraceID correlates the run's log entries.
	TraceID string `json:"trace_id"`
	// Launcher is the launcher name used for the run.
	Launcher string `json:"launcher"`
	// Provider is the provider name used for the run.
	Provider string `json:"provider"`
	// RunID is the provider-defined run identity.
	RunID string `json:"run_id"`
	// State is the last lifecycle state the provider reported.
	State string `json:"state"`
}

// Snapshot is the complete reported state of the scheduler.
type Snapshot struct {
	// GeneratedAt is when the snapshot was produced.
	GeneratedAt time.Time `json:"generated_at"`
	// TasksRoot is the scanned tasks folder.
	TasksRoot string `json:"tasks_root"`
	// Tasks holds one entry per known task, sorted by id.
	Tasks []TaskStatus `json:"tasks"`
}

// Find returns the status of one task.
func (s Snapshot) Find(id string) (TaskStatus, bool) {
	for _, status := range s.Tasks {
		if status.ID == id {
			return status, true
		}
	}
	return TaskStatus{}, false
}

// LaunchRequest asks for one immediate run of a task.
type LaunchRequest struct {
	// TaskID is the task to run.
	TaskID string `json:"task_id"`
	// Wait blocks until the run finishes when true. A CLI uses it to report the
	// outcome; the scheduler itself never waits.
	Wait bool `json:"wait"`
}

// LaunchResult is the outcome of a launch request.
type LaunchResult struct {
	// TaskID is the task that was launched.
	TaskID string `json:"task_id"`
	// PID is the process id of the run's process group leader.
	PID int `json:"pid"`
	// TraceID correlates the run's log entries.
	TraceID string `json:"trace_id"`
	// Skipped is true when the task was already running, so no new run started.
	Skipped bool `json:"skipped"`
	// Record is the completed run, present only when Wait was requested.
	Record *RunRecord `json:"record"`
}

// StopRequest asks to stop a running task.
type StopRequest struct {
	// TaskID is the task whose run should stop.
	TaskID string `json:"task_id"`
	// Force asks the provider for an immediate stop instead of a graceful one.
	Force bool `json:"force"`
}

// StopResult is the outcome of a stop request.
type StopResult struct {
	// TaskID is the task that was stopped.
	TaskID string `json:"task_id"`
	// PID is the process id of the run that was asked to stop.
	PID int `json:"pid"`
	// Forced is true when the caller asked for a forced stop. The scheduler
	// forwards the request to the provider; it does not choose the signal.
	Forced bool `json:"forced"`
	// BestEffort is true when the stop was issued for a run the scheduler is no
	// longer supervising, using the record the previous supervisor left in the
	// lock file. Such a stop is a request forwarded to the provider, not a
	// guarantee: the scheduler holds no context to cancel and cannot confirm the
	// run ended. A caller must not read it as "the run is stopped".
	BestEffort bool `json:"best_effort"`
}

// Controller is the standardized control contract.
//
// Every transport implements its own request decoding and calls these methods.
// The daemon is the only implementation, so behaviour cannot diverge between
// transports.
type Controller interface {
	// Launch starts one run of a task now.
	Launch(request LaunchRequest) (LaunchResult, error)
	// Status reports the current state of every task.
	Status() (Snapshot, error)
	// Stop actively stops a running task.
	Stop(request StopRequest) (StopResult, error)
}
