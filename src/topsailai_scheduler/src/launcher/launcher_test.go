package launcher

import (
	"strings"
	"testing"
	"time"

	"topsailai_scheduler/task"
)

// sampleTask returns a task with every path populated so placeholder expansion
// can be asserted exactly.
func sampleTask() task.Task {
	return task.Task{
		ID:           "data/work",
		Dir:          "/tasks/data",
		Stem:         "work",
		YAMLPath:     "/tasks/data/work.yaml",
		MarkdownPath: "/tasks/data/work.md",
		LockPath:     "/tasks/data/work.lock",
		Spec: task.Spec{
			Schedule: "@daily",
		},
	}
}

// sampleDefaults returns defaults distinct from the task values so a fallback is
// distinguishable from an override.
func sampleDefaults() Defaults {
	return Defaults{
		Workspace: "/default",
		Timeout:   30 * time.Minute,
	}
}

// TestRegistryRejectsDuplicate verifies that registering one name twice is an
// error, because the effective launcher would otherwise depend on init order.
func TestRegistryRejectsDuplicate(t *testing.T) {
	registry := NewRegistry()
	if err := registry.Register("x", func() Launcher { return Command{} }); err != nil {
		t.Fatalf("first register failed: %v", err)
	}
	if err := registry.Register("x", func() Launcher { return Agent{} }); err == nil {
		t.Fatal("expected a duplicate registration to be rejected")
	}
}

// TestRegistryRejectsEmptyName verifies that an unnamed launcher is rejected.
func TestRegistryRejectsEmptyName(t *testing.T) {
	registry := NewRegistry()
	if err := registry.Register("  ", func() Launcher { return Command{} }); err == nil {
		t.Fatal("expected an empty name to be rejected")
	}
}

// TestRegistryRejectsNilFactory verifies that a nil factory is rejected instead
// of panicking later at launch time.
func TestRegistryRejectsNilFactory(t *testing.T) {
	registry := NewRegistry()
	if err := registry.Register("x", nil); err == nil {
		t.Fatal("expected a nil factory to be rejected")
	}
}

// TestRegistryGetUnknown verifies that an unknown launcher name is an error that
// lists the available names, so a typo is diagnosable from the message.
func TestRegistryGetUnknown(t *testing.T) {
	registry := DefaultRegistry()
	_, err := registry.Get("nope")
	if err == nil {
		t.Fatal("expected an error for an unknown launcher")
	}
	if !strings.Contains(err.Error(), NameAgent) || !strings.Contains(err.Error(), NameCommand) {
		t.Errorf("expected the available names in the message, got %q", err.Error())
	}
}

// TestRegistryNamesSorted verifies that the built-in names are reported sorted,
// so log output and error messages are stable.
func TestRegistryNamesSorted(t *testing.T) {
	names := DefaultRegistry().Names()
	if len(names) != 2 || names[0] != NameAgent || names[1] != NameCommand {
		t.Errorf("expected [agent command], got %v", names)
	}
}

// TestRegistryGetInvokesFactoryEachTime verifies that every lookup builds a new
// launcher, so a stateful launcher cannot leak state between tasks.
//
// The built-in launchers are empty structs and therefore compare equal, so the
// factory call count is the property that can actually be asserted.
func TestRegistryGetInvokesFactoryEachTime(t *testing.T) {
	registry := NewRegistry()
	calls := 0
	if err := registry.Register("counting", func() Launcher {
		calls++
		return Command{}
	}); err != nil {
		t.Fatalf("register failed: %v", err)
	}

	for i := 0; i < 3; i++ {
		if _, err := registry.Get("counting"); err != nil {
			t.Fatalf("get counting: %v", err)
		}
	}
	if calls != 3 {
		t.Errorf("expected the factory to run 3 times, got %d", calls)
	}
}

// TestExpandReplacesEveryPlaceholder verifies that each documented placeholder
// resolves to its task value.
func TestExpandReplacesEveryPlaceholder(t *testing.T) {
	item := sampleTask()
	cases := map[string]string{
		PlaceholderTask:      item.MarkdownPath,
		PlaceholderTaskID:    item.ID,
		PlaceholderTaskDir:   item.Dir,
		PlaceholderStem:      item.Stem,
		PlaceholderWorkspace: "/work/demo",
	}
	for placeholder, want := range cases {
		if got := Expand(placeholder, item, "/work/demo"); got != want {
			t.Errorf("expanding %q: expected %q, got %q", placeholder, want, got)
		}
	}
}

// TestExpandLeavesUnknownText verifies that ordinary text is untouched, so an
// argument is never mangled.
func TestExpandLeavesUnknownText(t *testing.T) {
	got := Expand("--flag=value", sampleTask(), "/work")
	if got != "--flag=value" {
		t.Errorf("expected the argument unchanged, got %q", got)
	}
}

// TestExpandKeepsSpacesAsOneArgument verifies that expansion is a plain string
// replacement, so a path with spaces stays a single argv entry.
func TestExpandKeepsSpacesAsOneArgument(t *testing.T) {
	item := sampleTask()
	item.MarkdownPath = "/tasks/my folder/work.md"

	expanded := ExpandAll([]string{PlaceholderTask}, item, "/work")
	if len(expanded) != 1 {
		t.Fatalf("expected one argument, got %d", len(expanded))
	}
	if expanded[0] != "/tasks/my folder/work.md" {
		t.Errorf("expected the path with spaces intact, got %q", expanded[0])
	}
}

// TestCommandRequiresCommand verifies that the command launcher refuses a task
// with no command, because there is nothing to run.
func TestCommandRequiresCommand(t *testing.T) {
	item := sampleTask()
	if _, err := (Command{}).Build(item, sampleDefaults()); err == nil {
		t.Fatal("expected an error when the command launcher has no command")
	}
}

// TestCommandBuildsRequest verifies that the command launcher passes the
// expanded arguments and the resolved workspace.
func TestCommandBuildsRequest(t *testing.T) {
	item := sampleTask()
	item.Spec.Launcher = NameCommand
	item.Spec.Command = "/bin/echo"
	item.Spec.Args = []string{PlaceholderTaskID, PlaceholderStem}
	item.Spec.Workspace = "/work/task"

	request, err := (Command{}).Build(item, sampleDefaults())
	if err != nil {
		t.Fatalf("Build failed: %v", err)
	}
	if request.Command != "/bin/echo" {
		t.Errorf("unexpected command %q", request.Command)
	}
	if len(request.Args) != 2 || request.Args[0] != "data/work" || request.Args[1] != "work" {
		t.Errorf("unexpected args %v", request.Args)
	}
	if request.Workspace != "/work/task" {
		t.Errorf("expected the task workspace, got %q", request.Workspace)
	}
	if request.Timeout != 30*time.Minute {
		t.Errorf("expected the default timeout, got %v", request.Timeout)
	}
}

// TestCommandFallsBackToDefaultWorkspace verifies that an unset task workspace
// uses the scheduler default.
func TestCommandFallsBackToDefaultWorkspace(t *testing.T) {
	item := sampleTask()
	item.Spec.Command = "/bin/echo"

	request, err := (Command{}).Build(item, sampleDefaults())
	if err != nil {
		t.Fatalf("Build failed: %v", err)
	}
	if request.Workspace != "/default" {
		t.Errorf("expected the default workspace, got %q", request.Workspace)
	}
}

// TestCommandTaskTimeoutWins verifies that a task timeout overrides the default.
func TestCommandTaskTimeoutWins(t *testing.T) {
	item := sampleTask()
	item.Spec.Command = "/bin/echo"
	item.Spec.Timeout = task.Duration{Duration: 90 * time.Second}

	request, err := (Command{}).Build(item, sampleDefaults())
	if err != nil {
		t.Fatalf("Build failed: %v", err)
	}
	if request.Timeout != 90*time.Second {
		t.Errorf("expected the task timeout, got %v", request.Timeout)
	}
}

// TestCommandEnvCarriesOnlyTheTaskEnvironment verifies that the launcher adds no
// scheduler-owned variable. The provider is an independent project, so any
// variable it needs is its own business and must not be injected here.
func TestCommandEnvCarriesOnlyTheTaskEnvironment(t *testing.T) {
	item := sampleTask()
	item.Spec.Command = "/bin/echo"
	item.Spec.Env = map[string]string{"EXTRA": "value"}

	request, err := (Command{}).Build(item, sampleDefaults())
	if err != nil {
		t.Fatalf("Build failed: %v", err)
	}

	if len(request.Env) != 1 {
		t.Fatalf("expected only the task environment, got %v", request.Env)
	}
	if request.Env["EXTRA"] != "value" {
		t.Errorf("expected the task environment to survive, got %v", request.Env)
	}
	if _, found := request.Env["TOPSAILAI_TASK"]; found {
		t.Error("expected no scheduler-owned variable in the environment")
	}
}

// TestAgentLeavesTheInvocationToTheProvider verifies that the agent launcher
// supplies no executable. The provider owns the command line, so an empty
// command is the signal that the provider decides.
func TestAgentLeavesTheInvocationToTheProvider(t *testing.T) {
	item := sampleTask()
	item.Spec.Args = []string{"--extra"}

	request, err := (Agent{}).Build(item, sampleDefaults())
	if err != nil {
		t.Fatalf("Build failed: %v", err)
	}
	if request.Command != "" {
		t.Errorf("expected the provider to choose the command, got %q", request.Command)
	}
	if len(request.Args) != 1 || request.Args[0] != "--extra" {
		t.Errorf("expected only the task arguments, got %v", request.Args)
	}
}

// TestAgentIgnoresTheTaskCommand verifies that a task command does not leak into
// the agent launcher. Honouring it there would let a task silently replace the
// provider's invocation, which is the provider's decision to make.
func TestAgentIgnoresTheTaskCommand(t *testing.T) {
	item := sampleTask()
	item.Spec.Command = "/custom/agent"

	request, err := (Agent{}).Build(item, sampleDefaults())
	if err != nil {
		t.Fatalf("Build failed: %v", err)
	}
	if request.Command != "" {
		t.Errorf("expected the agent launcher to ignore the task command, got %q", request.Command)
	}

	commandRequest, err := (Command{}).Build(item, sampleDefaults())
	if err != nil {
		t.Fatalf("Build failed: %v", err)
	}
	if commandRequest.Command != "/custom/agent" {
		t.Errorf("expected the command launcher to honour the task command, got %q", commandRequest.Command)
	}
}

// TestAgentName verifies the names used in task YAML.
func TestAgentName(t *testing.T) {
	if (Agent{}).Name() != NameAgent {
		t.Errorf("expected %q, got %q", NameAgent, (Agent{}).Name())
	}
	if (Command{}).Name() != NameCommand {
		t.Errorf("expected %q, got %q", NameCommand, (Command{}).Name())
	}
}
