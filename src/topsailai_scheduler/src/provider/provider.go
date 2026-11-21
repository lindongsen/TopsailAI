// Package provider defines the standard seam between the scheduler and whatever
// actually runs a task.
//
// The scheduler is a process supervisor. It starts a run, observes whether that
// run is still alive, and stops it on request. It never decides whether the work
// succeeded: the success criteria belong to the task's Markdown content, which
// the provider reads.
//
// A provider is an independent program. It is not linked into the scheduler and
// is maintained as its own project, so this seam is a process-level protocol
// rather than a Go interface alone. The CLI type in this package adapts any
// executable that speaks the protocol documented in docs/Provider_Contract.md,
// which is what lets a provider be written, versioned and released separately.
//
// Three operations form the contract:
//
//	Start  begin one run and return a handle identifying it
//	Poll   report whether that run is still alive
//	Stop   ask that run to end
//
// A handle is opaque to the scheduler. It carries whatever identity the provider
// needs to answer a later Poll, so a provider may key on a session id, a job id,
// a container name or a pid without the scheduler knowing which.
package provider

import (
	"context"
	"fmt"
	"sort"
	"strings"
	"sync"
	"time"
)

// ProtocolVersion is the version of the CLI protocol this package speaks.
//
// A provider may report the version it implements in its start receipt. The
// adapter refuses a version it does not understand instead of guessing, so a
// future protocol revision cannot be silently misread as the current one.
const ProtocolVersion = 1

// State is the lifecycle state of one run as reported by a provider.
//
// There is deliberately no "succeeded" state. A provider reports whether the
// process is alive, not whether the work was good; that judgement belongs to the
// task content.
type State string

// Run states reported by Poll.
const (
	// StateRunning means the run is still in progress.
	StateRunning State = "running"
	// StateFinished means the run has ended. It says nothing about whether the
	// work succeeded.
	StateFinished State = "finished"
	// StateUnknown means the provider cannot determine the state. It is an
	// honest answer, not a failure: a provider that lost its record, or whose
	// own status call failed, must say so rather than report a guess.
	StateUnknown State = "unknown"
)

// ParseState converts a reported state string into a State.
//
// An unrecognised string is an error rather than a default. Treating an unknown
// word as "finished" would end supervision of a run that may still be working,
// and treating it as "running" would supervise forever; refusing to guess is the
// only safe reading.
func ParseState(value string) (State, error) {
	switch State(strings.TrimSpace(value)) {
	case StateRunning:
		return StateRunning, nil
	case StateFinished:
		return StateFinished, nil
	case StateUnknown:
		return StateUnknown, nil
	default:
		return "", fmt.Errorf("unknown run state %q: want %q, %q or %q",
			value, StateRunning, StateFinished, StateUnknown)
	}
}

// Request describes one run to start.
type Request struct {
	// TaskID is the task identity, for example "data/work".
	TaskID string
	// TaskPath is the absolute path of the task Markdown content.
	TaskPath string
	// TaskDir is the absolute folder holding the task files.
	TaskDir string
	// Workspace is the working directory the run should use.
	Workspace string
	// Command is the executable the task asks to run. It is empty when the
	// provider decides for itself, which is the case for a provider that wraps
	// one specific tool.
	Command string
	// Args are the arguments for Command, with placeholders already expanded.
	Args []string
	// Env holds extra environment variables for this run only.
	Env map[string]string
	// Timeout bounds the run. Zero means no timeout.
	Timeout time.Duration
}

// Handle identifies one started run.
//
// The scheduler stores a handle and hands it back unchanged, so a provider is
// free to encode any identity it needs. ID is the only required field: without
// it a later Poll cannot be answered.
type Handle struct {
	// Provider is the provider name that produced the handle.
	Provider string
	// ID is the provider-defined run identity, for example a session id.
	ID string
	// PID is the process id of the run, when the provider reports one. It is
	// for observability only: a pid can be reused, so it must never be the sole
	// key for a later Poll.
	PID int
	// StartedAt is when the scheduler asked for the run.
	StartedAt time.Time
}

// Observation is what a provider reports about a run.
type Observation struct {
	// State is the lifecycle state.
	State State
	// ExitCode is the run's exit status when the provider knows it. It is a
	// lifecycle fact, not a verdict: a non-zero code may mean the work failed,
	// or that the provider's wrapper exited, and the scheduler does not decide
	// which.
	ExitCode int
	// Detail is free-form provider text for logs and diagnostics.
	Detail string
}

// Provider starts, observes and stops runs of one kind.
//
// Implementations must be safe for concurrent use: the scheduler polls several
// runs at once.
type Provider interface {
	// Name returns the provider identity, which is the absolute path of its
	// executable. A path identifies one program exactly, so two runs of the same
	// executable match during reconciliation and a moved executable is reported
	// as a mismatch instead of being guessed at.
	Name() string
	// Start begins one run and returns its handle.
	Start(ctx context.Context, request Request) (Handle, error)
	// Poll reports the state of a run previously started.
	Poll(ctx context.Context, handle Handle) (Observation, error)
	// Stop asks a run to end.
	Stop(ctx context.Context, handle Handle) error
}

// Factory creates a provider. It is a function so a provider needing
// configuration can be constructed per registry.
type Factory func() Provider

// Registry holds the available providers by name.
type Registry struct {
	mu        sync.RWMutex
	factories map[string]Factory
}

// NewRegistry returns an empty registry.
func NewRegistry() *Registry {
	return &Registry{factories: make(map[string]Factory)}
}

// Register adds a provider factory under name.
//
// Registering a name twice is an error rather than a silent replacement: two
// implementations of one name would make the effective behaviour depend on
// initialisation order.
func (r *Registry) Register(name string, factory Factory) error {
	trimmed := strings.TrimSpace(name)
	if trimmed == "" {
		return fmt.Errorf("provider name must not be empty")
	}
	if factory == nil {
		return fmt.Errorf("provider %q has a nil factory", trimmed)
	}

	r.mu.Lock()
	defer r.mu.Unlock()
	if _, exists := r.factories[trimmed]; exists {
		return fmt.Errorf("provider %q is already registered", trimmed)
	}
	r.factories[trimmed] = factory
	return nil
}

// Get returns the provider registered under name.
func (r *Registry) Get(name string) (Provider, error) {
	trimmed := strings.TrimSpace(name)

	r.mu.RLock()
	factory, exists := r.factories[trimmed]
	r.mu.RUnlock()

	if !exists {
		return nil, fmt.Errorf("unknown provider %q: available providers are %s",
			trimmed, strings.Join(r.Names(), ", "))
	}
	return factory(), nil
}

// Names returns the registered provider names, sorted.
func (r *Registry) Names() []string {
	r.mu.RLock()
	defer r.mu.RUnlock()

	names := make([]string, 0, len(r.factories))
	for name := range r.factories {
		names = append(names, name)
	}
	sort.Strings(names)
	return names
}
