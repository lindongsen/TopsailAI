package tui

import (
	"context"
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"time"

	"topsailai_agent_cluster/internal/protocol"
)

// Trigger script location and budgets.
//
// The default script lives beside the per-user CLI configuration, so an operator
// installs one file and every watch in that account finds it. The lifetime is
// short on purpose: a notification script that has not finished in five seconds
// is already useless to an operator who is watching the screen, and a longer
// bound would only delay the next transition.
const (
	// triggerHomeRelativeDir is the per-user configuration directory the CLI
	// already reads, so a trigger script needs no second convention.
	triggerHomeRelativeDir = ".topsailai"
	// defaultTriggerFileName is the script name used when --trigger carries no
	// path. It names the event rather than the command, so a future event can
	// add its own file without renaming this one.
	defaultTriggerFileName = "topsailai-agent-cluster.on-state-change.trigger"
	// defaultTriggerTimeout bounds one script run.
	defaultTriggerTimeout = 5 * time.Second
	// triggerWaitDelay bounds how long Wait blocks after cancellation, so a
	// grandchild that inherited the pipes cannot keep the REPL waiting.
	triggerWaitDelay = 5 * time.Second
	// triggerMaxStreamBytes bounds one captured script stream. The output is
	// never rendered, so this only prevents an unbounded read from exhausting
	// REPL memory.
	triggerMaxStreamBytes = 16 << 10
)

// triggerEventName is the value of AGENT_CLUSTER_EVENT for a state transition.
// A script dispatches on this value, so a future event type is a new value
// rather than a new payload shape.
const triggerEventName = "state_change"

// TriggerEvent is the complete description of one observed transition. It
// carries every field a script needs to decide what to do, because a script
// cannot query the cluster itself: it runs as a bounded child process with no
// credentials.
type TriggerEvent struct {
	Event              string
	State              string
	PreviousState      string
	EndpointID         string
	ClusterSessionID   string
	ProviderSessionID  string
	SessionName        string
	ProviderGeneration string
	AdapterID          string
	ProjectWorkspace   string
	Unverified         bool
	Stale              bool
	// ObservedAtMS is the provider observation time in epoch milliseconds, or
	// empty when the report carried none. It is forwarded because the trigger
	// fires on a sampled state, so a script must be able to tell how old the
	// observation is instead of assuming it happened now.
	ObservedAtMS string
}

// TriggerRunner executes one trigger script. It is an interface so a test can
// observe the invocation without starting a real process.
type TriggerRunner interface {
	// RunTrigger executes path with the supplied environment. A non-zero exit is
	// returned as an error, because a failed notification is worth reporting.
	RunTrigger(ctx context.Context, path string, environment []string) error
}

// shouldTrigger decides whether one observed transition fires the script.
//
// Only running -> waiting_input fires today. The predicate is one function so a
// future transition is one added clause rather than a second detection path,
// and so the rule is testable without a controller, a ticker or a script.
func shouldTrigger(previous, next string) bool {
	return previous == protocol.SessionStateRunning && next == protocol.SessionStateWaitingInput
}

// triggerKey is the identity a baseline is remembered against. It is the same
// identity the row table uses, so a row number can never be mistaken for a
// session and a replaced process is never mistaken for the same one.
type triggerKey struct {
	EndpointID         string
	ClusterSessionID   string
	ProviderGeneration string
}

// triggerTracker remembers the last observed state per session identity.
//
// A baseline is required because the trigger fires on a transition, not on a
// state. Without it, arming watch would fire once for every session already
// waiting for input, and a session that stays waiting would fire on every tick.
type triggerTracker struct {
	states map[triggerKey]string
}

// observe records the current states and returns the transitions that fire.
//
// A session seen for the first time only establishes a baseline, and a session
// whose generation changed is a different process, so it also only establishes
// a baseline. Keys that are no longer reported are dropped, so a long watch
// cannot grow the baseline without bound.
func (t *triggerTracker) observe(rows []SessionRow) []TriggerEvent {
	if t.states == nil {
		t.states = make(map[triggerKey]string, len(rows))
	}
	seen := make(map[triggerKey]struct{}, len(rows))
	events := make([]TriggerEvent, 0, 1)
	for _, row := range rows {
		key := triggerKey{EndpointID: row.EndpointID, ClusterSessionID: row.ClusterSessionID, ProviderGeneration: row.ProviderGeneration}
		seen[key] = struct{}{}
		previous, known := t.states[key]
		t.states[key] = row.State
		if !known || !shouldTrigger(previous, row.State) {
			continue
		}
		events = append(events, TriggerEvent{
			Event:              triggerEventName,
			State:              row.State,
			PreviousState:      previous,
			EndpointID:         row.EndpointID,
			ClusterSessionID:   row.ClusterSessionID,
			ProviderSessionID:  row.ProviderSessionID,
			SessionName:        row.ProviderDisplayName,
			ProviderGeneration: row.ProviderGeneration,
			AdapterID:          row.AdapterID,
			ProjectWorkspace:   row.ProviderProjectWorkspace,
			Unverified:         row.Unverified,
			Stale:              row.Stale,
			ObservedAtMS:       observedAtMS(row.LastSuccessAtMS),
		})
	}
	for key := range t.states {
		if _, ok := seen[key]; !ok {
			delete(t.states, key)
		}
	}
	return events
}

// observedAtMS renders an optional observation time as a decimal string.
func observedAtMS(value *int64) string {
	if value == nil {
		return ""
	}
	return strconv.FormatInt(*value, 10)
}

// triggerEnvironment builds the child environment from a whitelist.
//
// The REPL process environment carries the cluster credentials, including the
// map of every endpoint token. Inheriting it would hand each notification script
// the authority to operate the whole fleet, so only the variables a script needs
// to resolve its interpreter and locate its own configuration are forwarded,
// plus the payload. A whitelist is used rather than a denylist because a new
// credential variable would silently leak through a denylist.
func triggerEnvironment(event TriggerEvent) []string {
	inherited := make(map[string]string, len(os.Environ()))
	for _, entry := range os.Environ() {
		if index := strings.IndexByte(entry, '='); index > 0 {
			inherited[entry[:index]] = entry[index+1:]
		}
	}
	environment := make([]string, 0, 20)
	for _, name := range []string{"PATH", "HOME", "LANG", "LC_ALL", "TZ", "TMPDIR"} {
		if value, ok := inherited[name]; ok {
			environment = append(environment, name+"="+value)
		}
	}
	// A dumb terminal keeps a script from emitting escape sequences that would
	// corrupt the table the editor owns.
	environment = append(environment, "TERM=dumb")
	return append(environment,
		"AGENT_CLUSTER_EVENT="+event.Event,
		"AGENT_CLUSTER_STATE="+event.State,
		"AGENT_CLUSTER_PREVIOUS_STATE="+event.PreviousState,
		"AGENT_CLUSTER_ENDPOINT_ID="+event.EndpointID,
		"AGENT_CLUSTER_CLUSTER_SESSION_ID="+event.ClusterSessionID,
		"AGENT_CLUSTER_PROVIDER_SESSION_ID="+event.ProviderSessionID,
		"AGENT_CLUSTER_SESSION_NAME="+event.SessionName,
		"AGENT_CLUSTER_PROVIDER_GENERATION="+event.ProviderGeneration,
		"AGENT_CLUSTER_ADAPTER_ID="+event.AdapterID,
		"AGENT_CLUSTER_PROJECT_WORKSPACE="+event.ProjectWorkspace,
		"AGENT_CLUSTER_UNVERIFIED="+strconv.FormatBool(event.Unverified),
		"AGENT_CLUSTER_STALE="+strconv.FormatBool(event.Stale),
		"AGENT_CLUSTER_OBSERVED_AT_MS="+event.ObservedAtMS,
	)
}

// resolveTriggerScript turns the parsed --trigger intent into one absolute path.
//
// An explicit path is validated strictly, because the operator named it: a
// missing or non-executable file is an error rather than a silent no-op. The
// default path is validated leniently, because the operator only asked for the
// convention: an absent script is reported as a note so the banner never claims
// a script will run when none is installed.
func resolveTriggerScript(request watchRequest) (path string, note string, err error) {
	if !request.TriggerSet {
		return "", "", nil
	}
	if request.TriggerPath != "" {
		resolved, absErr := filepath.Abs(request.TriggerPath)
		if absErr != nil {
			return "", "", fmt.Errorf("trigger script %q is not a usable path: %w", request.TriggerPath, absErr)
		}
		info, statErr := os.Stat(resolved)
		if statErr != nil {
			return "", "", fmt.Errorf("trigger script %q is unavailable: %w", request.TriggerPath, statErr)
		}
		if info.IsDir() {
			return "", "", fmt.Errorf("trigger script %q is a directory", request.TriggerPath)
		}
		if info.Mode().Perm()&0o111 == 0 {
			return "", "", fmt.Errorf("trigger script %q is not executable", request.TriggerPath)
		}
		return resolved, "", nil
	}
	home, homeErr := os.UserHomeDir()
	if homeErr != nil {
		return "", "trigger: no script installed because the home directory is unknown", nil
	}
	resolved := filepath.Join(home, triggerHomeRelativeDir, defaultTriggerFileName)
	info, statErr := os.Stat(resolved)
	if statErr != nil {
		return "", "trigger: no script installed at " + resolved, nil
	}
	if info.IsDir() {
		return "", "trigger: " + resolved + " is a directory, so no script runs", nil
	}
	if info.Mode().Perm()&0o111 == 0 {
		return "", "trigger: " + resolved + " is not executable, so no script runs", nil
	}
	return resolved, "", nil
}

// execTriggerRunner runs a trigger script without a shell.
type execTriggerRunner struct {
	timeout time.Duration
}

// NewExecTriggerRunner returns the production trigger runner.
func NewExecTriggerRunner() TriggerRunner { return execTriggerRunner{} }

// RunTrigger executes path directly and captures bounded output.
//
// The script is executed as one argv array with no shell, so a payload value can
// never be reinterpreted as syntax. Output is captured rather than forwarded,
// because the editor owns the terminal and a script that wrote to it would
// corrupt the table.
func (r execTriggerRunner) RunTrigger(parent context.Context, path string, environment []string) error {
	timeout := r.timeout
	if timeout <= 0 {
		timeout = defaultTriggerTimeout
	}
	ctx, cancel := context.WithTimeout(parent, timeout)
	defer cancel()
	cmd := exec.CommandContext(ctx, path)
	cmd.Env = environment
	// The default cancellation kills only the direct child, which leaves any
	// process the script spawned running after the REPL reported the trigger
	// finished.
	configureTriggerProcessGroup(cmd)
	cmd.Cancel = func() error { return killTriggerProcessGroup(cmd) }
	cmd.WaitDelay = triggerWaitDelay
	stdout, err := cmd.StdoutPipe()
	if err != nil {
		return fmt.Errorf("prepare trigger script stdout: %w", err)
	}
	stderr, err := cmd.StderrPipe()
	if err != nil {
		return fmt.Errorf("prepare trigger script stderr: %w", err)
	}
	if err := cmd.Start(); err != nil {
		return fmt.Errorf("start trigger script %q: %w", filepath.Base(path), err)
	}
	// Both pipes must be drained concurrently: a script that fills stderr while
	// the caller is still reading stdout would block until the timeout.
	var outBuf, errBuf []byte
	var wait sync.WaitGroup
	wait.Add(2)
	go func() {
		defer wait.Done()
		outBuf, _ = readTriggerStream(stdout)
	}()
	go func() {
		defer wait.Done()
		errBuf, _ = readTriggerStream(stderr)
	}()
	wait.Wait()
	waitErr := cmd.Wait()
	if ctx.Err() != nil {
		return fmt.Errorf("trigger script %q exceeded its %s lifetime", filepath.Base(path), timeout)
	}
	if waitErr != nil {
		var exitErr *exec.ExitError
		if errors.As(waitErr, &exitErr) {
			return fmt.Errorf("trigger script %q exited %d: %s", filepath.Base(path), exitErr.ExitCode(), triggerDiagnostic(errBuf, outBuf))
		}
		return fmt.Errorf("wait for trigger script %q: %w", filepath.Base(path), waitErr)
	}
	return nil
}

// readTriggerStream reads at most triggerMaxStreamBytes from one stream.
func readTriggerStream(reader io.Reader) ([]byte, bool) {
	data, err := io.ReadAll(io.LimitReader(reader, triggerMaxStreamBytes+1))
	if err != nil {
		return data, false
	}
	if len(data) > triggerMaxStreamBytes {
		return data[:triggerMaxStreamBytes], true
	}
	return data, false
}

// triggerDiagnostic flattens the captured output into one bounded line, so a
// failed script reports why it failed instead of only its exit code.
func triggerDiagnostic(stderr, stdout []byte) string {
	text := strings.TrimSpace(string(stderr))
	if text == "" {
		text = strings.TrimSpace(string(stdout))
	}
	if text == "" {
		return "no output"
	}
	return sanitizeInlineText(text)
}
