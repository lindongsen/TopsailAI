// Package launcher turns a task into a request for a provider.
//
// The scheduler never runs a task itself. It asks a launcher to describe the
// run, then hands that description to a provider, which is an independent
// program speaking the protocol in docs/Provider_Contract.md. The launcher is
// therefore the scheduler's own component: it knows about tasks, placeholders
// and defaults, and it produces a provider.Request. It knows nothing about how
// the provider starts, observes or stops the run.
//
// Two launchers are built in:
//
//	agent    the provider decides the invocation, the default
//	command  the task names the executable and its arguments
//
// A caller may register further launchers through Registry.Register.
package launcher

import (
	"fmt"
	"sort"
	"strings"
	"sync"
	"time"

	"topsailai_scheduler/provider"
	"topsailai_scheduler/task"
)

// Built-in launcher names.
const (
	// NameAgent lets the provider decide how the task is run.
	NameAgent = "agent"
	// NameCommand runs the executable the task names.
	NameCommand = "command"
)

// Placeholders available in a command launcher's arguments.
const (
	// PlaceholderTask is replaced by the absolute task Markdown path.
	PlaceholderTask = "{task}"
	// PlaceholderTaskID is replaced by the task id, for example "data/work".
	PlaceholderTaskID = "{task_id}"
	// PlaceholderTaskDir is replaced by the absolute folder holding the task.
	PlaceholderTaskDir = "{task_dir}"
	// PlaceholderStem is replaced by the shared filename stem.
	PlaceholderStem = "{stem}"
	// PlaceholderWorkspace is replaced by the resolved workspace.
	PlaceholderWorkspace = "{workspace}"
)

// Defaults carries the scheduler-wide values a launcher may fall back to.
//
// It is a plain struct rather than the config type so this package does not
// depend on configuration loading, and so a test can supply its own values.
type Defaults struct {
	// Workspace is the default working directory.
	Workspace string
	// Timeout bounds a run whose task sets no timeout.
	Timeout time.Duration
}

// Launcher builds the provider request for one task.
type Launcher interface {
	// Name returns the launcher name used in a task's YAML.
	Name() string
	// Build returns the provider request describing the run.
	Build(item task.Task, defaults Defaults) (provider.Request, error)
}

// Factory creates a launcher. It is a function so a launcher needing
// configuration can be constructed per registry.
type Factory func() Launcher

// Registry holds the available launchers by name.
type Registry struct {
	mu        sync.RWMutex
	factories map[string]Factory
}

// NewRegistry returns an empty registry.
func NewRegistry() *Registry {
	return &Registry{factories: make(map[string]Factory)}
}

// DefaultRegistry returns a registry with the built-in launchers registered.
func DefaultRegistry() *Registry {
	registry := NewRegistry()
	// The built-ins cannot fail to register: the names are distinct constants.
	_ = registry.Register(NameAgent, func() Launcher { return Agent{} })
	_ = registry.Register(NameCommand, func() Launcher { return Command{} })
	return registry
}

// Register adds a launcher factory under name.
//
// Registering a name twice is an error rather than a silent replacement: two
// implementations of one name would make the effective behaviour depend on
// initialisation order.
func (r *Registry) Register(name string, factory Factory) error {
	trimmed := strings.TrimSpace(name)
	if trimmed == "" {
		return fmt.Errorf("launcher name must not be empty")
	}
	if factory == nil {
		return fmt.Errorf("launcher %q has a nil factory", trimmed)
	}

	r.mu.Lock()
	defer r.mu.Unlock()
	if _, exists := r.factories[trimmed]; exists {
		return fmt.Errorf("launcher %q is already registered", trimmed)
	}
	r.factories[trimmed] = factory
	return nil
}

// Get returns the launcher registered under name.
func (r *Registry) Get(name string) (Launcher, error) {
	trimmed := strings.TrimSpace(name)

	r.mu.RLock()
	factory, exists := r.factories[trimmed]
	r.mu.RUnlock()

	if !exists {
		return nil, fmt.Errorf("unknown launcher %q: available launchers are %s",
			trimmed, strings.Join(r.Names(), ", "))
	}
	return factory(), nil
}

// Names returns the registered launcher names, sorted.
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

// Expand replaces the supported placeholders in one argument.
//
// Expansion is a plain string replacement, not a shell evaluation: an argument
// is passed to the child as one argv entry, so a path containing spaces stays a
// single argument and no quoting is required.
func Expand(argument string, item task.Task, workspace string) string {
	replacer := strings.NewReplacer(
		PlaceholderTask, item.MarkdownPath,
		PlaceholderTaskID, item.ID,
		PlaceholderTaskDir, item.Dir,
		PlaceholderStem, item.Stem,
		PlaceholderWorkspace, workspace,
	)
	return replacer.Replace(argument)
}

// ExpandAll expands every argument in the slice.
func ExpandAll(arguments []string, item task.Task, workspace string) []string {
	expanded := make([]string, 0, len(arguments))
	for _, argument := range arguments {
		expanded = append(expanded, Expand(argument, item, workspace))
	}
	return expanded
}

// resolveWorkspace returns the task workspace, falling back to the default.
func resolveWorkspace(item task.Task, defaults Defaults) string {
	if strings.TrimSpace(item.Spec.Workspace) != "" {
		return item.Spec.Workspace
	}
	return defaults.Workspace
}

// resolveTimeout returns the task timeout, falling back to the default.
func resolveTimeout(item task.Task, defaults Defaults) time.Duration {
	if item.Spec.Timeout.Duration > 0 {
		return item.Spec.Timeout.Duration
	}
	return defaults.Timeout
}

// taskEnv returns the task's own environment variables.
//
// The scheduler adds nothing of its own here. A variable that only one provider
// understands, such as the path of the task file for the TopsailAI agent, is
// that provider's business: the provider receives task_path in the protocol
// document and can set whatever it needs.
func taskEnv(item task.Task) map[string]string {
	if len(item.Spec.Env) == 0 {
		return nil
	}
	env := make(map[string]string, len(item.Spec.Env))
	for key, value := range item.Spec.Env {
		env[key] = value
	}
	return env
}
