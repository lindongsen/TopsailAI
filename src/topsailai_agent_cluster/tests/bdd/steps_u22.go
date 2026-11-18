package bdd

import (
	"encoding/json"
	"fmt"
	"strings"

	"github.com/cucumber/godog"
	"topsailai_agent_cluster/tests/harness"
)

// registerU22Steps registers real output snapshot scenarios.
func registerU22Steps(ctx *godog.ScenarioContext) {
	ctx.Step(`^a session with provider output$`, u22StartOutputCluster)
	ctx.Step(`^a session whose adapter does not support output reading$`, u22StartUnsupportedCluster)
	ctx.Step(`^a session with provider output larger than 32768 bytes$`, u22StartLargeOutputCluster)
	ctx.Step(`^I run the tui logs command with max bytes 65536$`, u22RunLargeLogs)
	ctx.Step(`^the output length is greater than 32768$`, u22AssertLargeOutput)
	ctx.Step(`^I run the tui logs command$`, u22RunLogs)
	ctx.Step(`^the logs command fails reporting "([^"]*)"$`, u22AssertLogsFailed)
	ctx.Step(`^I run the tui logs command with max bytes 16$`, u22RunBoundedLogs)
	ctx.Step(`^the output length is at most 16 and truncated$`, u22AssertBoundedOutput)
	ctx.Step(`^the output contains the provider output marker$`, u22AssertOutputMarker)
}

func u22StartOutputCluster() error { return u22StartCluster(harness.FaultInjection{}) }
func u22StartUnsupportedCluster() error {
	return u22StartCluster(harness.FaultInjection{OutputUnsupported: true})
}
func u22StartCluster(faults harness.FaultInjection) error {
	activeScenario.world = &World{}
	if err := activeScenario.world.StartRealCluster(faults); err != nil {
		return err
	}
	activeScenario.realCluster = activeScenario.world.realCluster
	if _, err := activeScenario.realCluster.BuildTUI(activeTest); err != nil {
		return fmt.Errorf("build TUI: %w", err)
	}
	return nil
}
func u22RunLogs() error {
	id, err := tuiResourceID()
	if err != nil {
		return err
	}
	stdout, stderr, code, runErr := activeScenario.realCluster.RunTUI("logs", "endpoint-1", id)
	// Both streams are captured because a failed read reports its error code on
	// stderr and exits non-zero, which is the contract the CLI adopted when it
	// stopped printing an error code as content. Reading stdout alone would make
	// the failure look like an empty successful read.
	activeScenario.lastBody, activeScenario.lastStatus = []byte(stdout+stderr), code
	// A non-zero exit is the expected outcome for the scenarios that assert a
	// failure, so it is not a step error here. Only a run that failed while
	// reporting success is a harness problem, which is the same rule
	// runPolicyProbe follows for the policy-refusal scenarios.
	if runErr != nil && code == 0 {
		return fmt.Errorf("run logs: %w stderr=%s", runErr, stderr)
	}
	return nil
}
func u22AssertOutputMarker() error {
	if !strings.Contains(string(activeScenario.lastBody), "provider output marker") {
		return fmt.Errorf("output marker missing: %s", activeScenario.lastBody)
	}
	return nil
}

// u22AssertLogsFailed proves a failed read is reported as a failure, not as
// content. Both halves are asserted because either one alone can pass for the
// wrong reason: a non-zero exit with no code leaves the operator without a
// reason, and the code printed on stdout with exit zero is exactly the defect
// that made a failed read indistinguishable from a successful one.
func u22AssertLogsFailed(code string) error {
	if activeScenario.lastStatus == 0 {
		return fmt.Errorf("logs exited 0 while reporting %q, want a non-zero exit: %s", code, activeScenario.lastBody)
	}
	if !strings.Contains(strings.ToLower(string(activeScenario.lastBody)), strings.ToLower(code)) {
		return fmt.Errorf("logs exit=%d does not report %q: %s", activeScenario.lastStatus, code, activeScenario.lastBody)
	}
	return nil
}
func u22StartLargeOutputCluster() error {
	return u22StartCluster(harness.FaultInjection{OutputSize: 65536})
}

func u22RunLargeLogs() error {
	id, err := tuiResourceID()
	if err != nil {
		return err
	}
	stdout, stderr, code, runErr := activeScenario.realCluster.RunTUI("--max-bytes", "65536", "logs", "endpoint-1", id)
	activeScenario.lastBody, activeScenario.lastStatus = []byte(stdout), code
	if runErr != nil {
		return fmt.Errorf("run large logs: %w stderr=%s", runErr, stderr)
	}
	return nil
}

func u22AssertLargeOutput() error {
	if len(activeScenario.lastBody) <= 32768 {
		return fmt.Errorf("output length=%d, want greater than 32768", len(activeScenario.lastBody))
	}
	return nil
}

func u22RunBoundedLogs() error {
	id, err := tuiResourceID()
	if err != nil {
		return err
	}
	stdout, stderr, code, runErr := activeScenario.realCluster.RunTUI("--json", "--max-bytes", "16", "logs", "endpoint-1", id)
	activeScenario.lastBody, activeScenario.lastStatus = []byte(stdout), code
	if runErr != nil {
		return fmt.Errorf("run bounded logs: %w stderr=%s", runErr, stderr)
	}
	return nil
}

func u22AssertBoundedOutput() error {
	var snapshot struct {
		Data      string `json:"data"`
		Truncated bool   `json:"truncated"`
	}
	if err := json.Unmarshal(activeScenario.lastBody, &snapshot); err != nil {
		return fmt.Errorf("decode bounded snapshot: %w", err)
	}
	if len(snapshot.Data) > 16 {
		return fmt.Errorf("data length=%d, want <=16", len(snapshot.Data))
	}
	if !snapshot.Truncated {
		return fmt.Errorf("snapshot is not truncated: %s", activeScenario.lastBody)
	}
	if !strings.HasPrefix(snapshot.Data, "provider output ") {
		return fmt.Errorf("output is not provider prefix: %q", snapshot.Data)
	}
	return nil
}
