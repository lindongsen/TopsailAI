package bdd

import (
	"fmt"
	"strings"

	"github.com/cucumber/godog"
	"topsailai_agent_cluster/internal/security"
	"topsailai_agent_cluster/tests/harness"
)

// registerOutputScopeSteps registers the read_output authorization scenarios.
//
// These scenarios exist because the output routes once served session output to
// any authenticated credential. Session output carries prompts, model answers,
// tool arguments and command results, so it is the most sensitive data the
// cluster holds. A unit test proves the handler refuses a narrowed credential;
// these scenarios prove the shipped binaries do it over a real WebSocket, which
// is the only way to show the check is wired into the running Server.
func registerOutputScopeSteps(ctx *godog.ScenarioContext) {
	ctx.Step(`^a real cluster whose credential may only view$`, startViewOnlyCluster)
	ctx.Step(`^a real cluster whose credential may read output$`, startReadOutputCluster)
	ctx.Step(`^the logs command is run with a credential that may only view$`, runLogsWithViewCredential)
	ctx.Step(`^the logs follow command is run with a credential that may only view$`, runLogsFollowWithViewCredential)
	ctx.Step(`^the logs command is run with a credential that may read output$`, runLogsWithReadOutputCredential)
	ctx.Step(`^the output request is refused for lack of read output permission$`, assertOutputRefusedForScope)
	ctx.Step(`^the follow request is refused for lack of read output permission$`, assertFollowRefusedForScope)
	ctx.Step(`^the output request returns provider output$`, assertOutputServed)
}

// startViewOnlyCluster starts a real cluster whose single credential holds only
// the view scope. Narrowing the scope is the whole point: an empty scope set is
// unrestricted, so a cluster started without this option would let the request
// through and the scenario would pass while proving nothing.
func startViewOnlyCluster() error {
	return startScopedCluster([]string{security.ScopeView})
}

// startReadOutputCluster starts a real cluster whose credential holds the
// read_output scope, so the scenario can prove the check admits a permitted
// caller instead of refusing everyone.
func startReadOutputCluster() error {
	return startScopedCluster([]string{security.ScopeReadOutput})
}

// startScopedCluster starts a real cluster with an explicitly narrowed scope set.
func startScopedCluster(scopes []string) error {
	if activeTest == nil {
		return fmt.Errorf("active BDD test is not initialized")
	}
	if activeScenario.world == nil {
		activeScenario.world = &World{}
	}
	cluster, err := harness.StartCluster(activeTest, harness.ClusterOptions{
		Environment: map[string]string{"AGENT_CLUSTER_AUTH_SCOPES": strings.Join(scopes, ",")},
	})
	if err != nil {
		return err
	}
	activeScenario.world.realCluster = cluster
	activeScenario.realCluster = cluster
	if _, err := cluster.BuildTUI(activeTest); err != nil {
		return fmt.Errorf("build CLI: %w", err)
	}
	return nil
}

// runLogsWithViewCredential runs one bounded output snapshot with a credential
// that lacks read_output. A refusal is the expected outcome, so a non-zero exit
// status is recorded rather than treated as a step failure.
func runLogsWithViewCredential() error {
	return runScopedLogs()
}

// runLogsWithReadOutputCredential runs the same snapshot with a credential that
// holds read_output, so the scenario can prove the check is not a blanket denial.
func runLogsWithReadOutputCredential() error {
	return runScopedLogs()
}

// runScopedLogs runs one logs command and records its result without judging it,
// because the two scenarios expect opposite outcomes from the same command.
func runScopedLogs() error {
	if activeScenario.realCluster == nil {
		return fmt.Errorf("real cluster is not running")
	}
	resourceID, err := tuiResourceID()
	if err != nil {
		return err
	}
	stdout, stderr, code, runErr := activeScenario.realCluster.RunTUI("logs", "endpoint-1", resourceID)
	activeScenario.lastBody = []byte(stdout + stderr)
	activeScenario.lastStatus = code
	// A non-zero exit is the expected outcome for the refused scenario, so only a
	// launch failure is reported here.
	if runErr != nil && code == 0 {
		return fmt.Errorf("run logs: %v stderr=%s", runErr, stderr)
	}
	return nil
}

// runLogsFollowWithViewCredential runs the streaming surface with a credential
// that lacks read_output. The follow route is covered separately because it was
// copied from the snapshot route and inherited the same missing check, so a fix
// applied to only one route would leave the other open.
func runLogsFollowWithViewCredential() error {
	if activeScenario.realCluster == nil {
		return fmt.Errorf("real cluster is not running")
	}
	resourceID, err := tuiResourceID()
	if err != nil {
		return err
	}
	stdout, stderr, code, runErr := activeScenario.realCluster.RunTUI("logs", "endpoint-1", resourceID, "--follow")
	activeScenario.lastBody = []byte(stdout + stderr)
	activeScenario.lastStatus = code
	if runErr != nil && code == 0 {
		return fmt.Errorf("run logs follow: %v stderr=%s", runErr, stderr)
	}
	return nil
}

// assertOutputRefusedForScope proves the snapshot was refused for the missing
// permission, and that no provider output reached the caller.
func assertOutputRefusedForScope() error {
	return assertRefusedForScope("output")
}

// assertFollowRefusedForScope proves the follow was refused for the missing
// permission, and that no provider output reached the caller.
func assertFollowRefusedForScope() error {
	return assertRefusedForScope("follow")
}

// assertRefusedForScope checks the refusal evidence shared by both surfaces.
//
// The assertion names the missing scope, because a generic failure could come
// from an unrelated defect and would let a broken cluster look like a working
// authorization check. It also rejects any provider output in the response, so a
// refusal that leaked data before failing cannot pass.
func assertRefusedForScope(surface string) error {
	text := string(activeScenario.lastBody)
	if activeScenario.lastStatus == 0 {
		return fmt.Errorf("the %s request succeeded with a credential that lacks read_output: %s", surface, text)
	}
	if !strings.Contains(text, security.ScopeReadOutput) {
		return fmt.Errorf("the %s refusal does not name the missing %q permission: %s", surface, security.ScopeReadOutput, text)
	}
	if !strings.Contains(text, "403") {
		return fmt.Errorf("the %s refusal does not report the forbidden status: %s", surface, text)
	}
	if strings.Contains(text, "provider output marker") {
		return fmt.Errorf("the %s refusal leaked provider output: %s", surface, text)
	}
	return nil
}

// assertOutputServed proves a credential holding read_output still receives the
// provider output, so the check narrows access instead of breaking the surface.
func assertOutputServed() error {
	text := string(activeScenario.lastBody)
	if activeScenario.lastStatus != 0 {
		return fmt.Errorf("the logs command failed with a credential that holds read_output: exit=%d output=%s", activeScenario.lastStatus, text)
	}
	if !strings.Contains(text, "provider output marker") {
		return fmt.Errorf("the logs command returned no provider output: %s", text)
	}
	return nil
}
