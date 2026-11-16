package genericcli

// The Provider CLI is started with the environment the Adapter was configured
// with. That wiring is one line, and it is the only thing that decides whether a
// Provider sees the configuration the operator exported for it.
//
// The defect this guards is not a wrong value but an absent one. `command.Env`
// set to nil makes Go inherit the parent environment, which looks identical to a
// correct pass-through in every test that only inspects the config struct. The
// two cases differ only in a real child process, so both directions are proven
// here with one: a configured value must arrive, and a value that exists only in
// the parent must not.
//
// The helper is selected by an argv sentinel rather than by an environment
// variable, because the environment is the subject under test. A sentinel carried
// in the environment would disappear in exactly the broken case, so the helper
// would skip and the failure would read as "the helper did not run" instead of
// naming the inheritance that actually happened.

import (
	"bytes"
	"context"
	"os"
	"strings"
	"testing"
	"time"
)

// environmentMarker is the variable the helper process reports. It is deliberately
// not a real setting, so a value inherited from the test runner cannot be mistaken
// for a configured one.
const environmentMarker = "AGENT_CLUSTER_TEST_ENVIRONMENT_MARKER"

// environmentHelperSentinel selects the child half. It travels in argv, which the
// runner always passes through, so the helper runs in both the correct and the
// broken case.
const environmentHelperSentinel = "--environment-helper"

// TestEnvironmentHelperProcess is the child half of the environment guard. It
// prints the marker it actually received and exits before the test framework
// prints its own summary, so the parent reads one line and nothing else.
func TestEnvironmentHelperProcess(t *testing.T) {
	if !hasArgument(os.Args, environmentHelperSentinel) {
		t.Skip("helper process only")
	}
	_, _ = os.Stdout.WriteString("marker=" + os.Getenv(environmentMarker))
	os.Exit(0)
}

// hasArgument reports whether argv contains one exact argument.
func hasArgument(arguments []string, wanted string) bool {
	for _, argument := range arguments {
		if argument == wanted {
			return true
		}
	}
	return false
}

// environmentHelperRunner builds a runner that re-executes this test binary as the
// Provider CLI, so the environment is observed by a real child process.
func environmentHelperRunner(t *testing.T, environment []string) *processRunner {
	t.Helper()
	executable, err := os.Executable()
	if err != nil {
		t.Fatalf("resolve test executable: %v", err)
	}
	runner, err := newProcessRunner(runnerConfig{
		executable:     executable,
		args:           []string{"-test.run=^TestEnvironmentHelperProcess$", "-test.count=1", "--", environmentHelperSentinel},
		environment:    environment,
		timeout:        20 * time.Second,
		maxStdinBytes:  1 << 20,
		maxStdoutBytes: 1 << 20,
		maxStderrBytes: 1 << 20,
		maxRecords:     10,
	})
	if err != nil {
		t.Fatalf("build helper runner: %v", err)
	}
	return runner
}

// runEnvironmentHelper starts the helper and returns what it printed.
func runEnvironmentHelper(t *testing.T, runner *processRunner) string {
	t.Helper()
	command := runner.command(context.Background())
	var stdout bytes.Buffer
	command.Stdout = &stdout
	command.Stderr = &bytes.Buffer{}
	if err := command.Run(); err != nil {
		t.Fatalf("run environment helper: %v", err)
	}
	return stdout.String()
}

// TestConfiguredEnvironmentReachesTheChild proves a value the Adapter was
// configured with arrives in the Provider process.
//
// Without this the Provider could be started with an empty environment and every
// setting the operator exported would be silently absent, which is the failure
// mode that makes a Provider resolve a different home and report zero rows with
// no error to explain it.
func TestConfiguredEnvironmentReachesTheChild(t *testing.T) {
	environment := []string{
		"PATH=" + os.Getenv("PATH"),
		environmentMarker + "=configured-value",
	}
	output := runEnvironmentHelper(t, environmentHelperRunner(t, environment))
	if !strings.Contains(output, "marker=configured-value") {
		t.Fatalf("the child printed %q, so the configured environment did not reach it", output)
	}
}

// TestConfiguredEnvironmentDoesNotInheritTheParent proves the configured
// environment is authoritative rather than a starting point.
//
// A nil environment makes Go inherit the parent, and an inherited environment is
// indistinguishable from a configured one when the value happens to be present in
// both. Here the marker exists only in the parent, so a child that reports it is
// reading an environment nobody configured.
func TestConfiguredEnvironmentDoesNotInheritTheParent(t *testing.T) {
	t.Setenv(environmentMarker, "inherited-value")
	environment := []string{"PATH=" + os.Getenv("PATH")}
	output := runEnvironmentHelper(t, environmentHelperRunner(t, environment))
	if strings.Contains(output, "inherited-value") {
		t.Fatalf("the child printed %q, so it inherited the parent environment instead of using the configured one", output)
	}
	if !strings.Contains(output, "marker=") {
		t.Fatalf("the child printed %q, so the helper did not run", output)
	}
}
