package bdd

import (
	"fmt"
	"net/http"
	"strings"
	"time"

	"github.com/cucumber/godog"
	"topsailai_agent_cluster/internal/protocol"
	"topsailai_agent_cluster/tests/harness"
)

// registerU21Steps registers real command-history, profile-validation, and empty-endpoint scenarios.
func registerU21Steps(ctx *godog.ScenarioContext) {
	ctx.Step(`^a session with at least one submitted command$`, u21SubmitHistoryCommand)
	ctx.Step(`^the output contains the command id prefix$`, u21AssertCommandIDPrefix)
	ctx.Step(`^the output contains the command status$`, u21AssertCommandStatus)
	ctx.Step(`^I submit a start command with an unknown profile revision$`, u21SubmitBadStart)
	ctx.Step(`^the command is rejected$`, u21AssertRejected)
	ctx.Step(`^a running cluster with one endpoint reporting no sessions$`, u21StartEmptyEndpoint)
	ctx.Step(`^I run the tui list command in human readable mode$`, u21RunHumanList)
	ctx.Step(`^the output contains the endpoint id$`, u21AssertEndpointID)
}

func u21SubmitHistoryCommand() error {
	if err := u21EnsureRealCluster(); err != nil {
		return err
	}
	id, err := activeScenario.world.SubmitRealCommand("message.send", "fixture-session", "fixture-generation", `{"text":"history"}`)
	if err != nil {
		return err
	}
	status, pollErr := activeScenario.world.PollRealCommand(id, 10*time.Second)
	if pollErr != nil {
		return pollErr
	}
	activeScenario.realCommandID = id
	activeScenario.realCommandStatus = status
	return nil
}

func u21RunHumanShow() error {
	id, err := tuiResourceID()
	if err != nil {
		return err
	}
	stdout, stderr, code, runErr := activeScenario.realCluster.RunTUI("show", id)
	activeScenario.lastBody = []byte(stdout)
	activeScenario.lastStatus = code
	if runErr != nil {
		return fmt.Errorf("run human show: %w; stderr=%s", runErr, stderr)
	}
	return nil
}

func u21AssertCommandIDPrefix() error {
	if !strings.Contains(string(activeScenario.lastBody), "bdd-real-") {
		return fmt.Errorf("human show output lacks command ID prefix: %s", activeScenario.lastBody)
	}
	return nil
}

func u21AssertCommandStatus() error {
	status := stringValue(activeScenario.realCommandStatus, "status", "Status")
	if status == "" || !strings.Contains(string(activeScenario.lastBody), status) {
		return fmt.Errorf("human show output lacks command status %q: %s", status, activeScenario.lastBody)
	}
	return nil
}

func u21SubmitBadStart() error {
	if err := u21EnsureRealCluster(); err != nil {
		return err
	}
	id := fmt.Sprintf("bdd-start-%d", time.Now().UnixNano())
	intent := map[string]any{
		"hash_version": "v1", "command_id": id, "issuer_id": "operator", "scope": "operator",
		"endpoint_id": "endpoint-1", "launch_profile_id": "fixture-main", "profile_revision": "unknown-revision",
		"operation": "agent.start", "operation_version": "v1", "capability_revision": "v1",
		"payload_schema_version": "v1", "payload": map[string]any{},
		"execute_before_at_ms": time.Now().Add(time.Minute).UnixMilli(),
	}
	status, body, err := activeScenario.world.realRequestE(http.MethodPost, "/api/v1/commands", intent)
	if err != nil {
		return err
	}
	if status != http.StatusAccepted && status != http.StatusOK {
		return fmt.Errorf("start submission status=%d body=%s", status, body)
	}
	activeScenario.realCommandID = id
	result, err := activeScenario.world.PollRealCommand(id, 10*time.Second)
	if err != nil {
		return err
	}
	activeScenario.realCommandStatus = result
	return nil
}

func u21AssertRejected() error {
	status := stringValue(activeScenario.realCommandStatus, "status", "Status")
	if status != string(protocol.StatusRejected) {
		return fmt.Errorf("status=%q, want rejected: %#v", status, activeScenario.realCommandStatus)
	}
	return nil
}

func u21EnsureRealCluster() error {
	if activeScenario.world == nil {
		activeScenario.world = &World{}
	}
	if activeScenario.world.realCluster != nil {
		return nil
	}
	if err := activeScenario.world.StartRealCluster(harness.FaultInjection{}); err != nil {
		return err
	}
	activeScenario.realCluster = activeScenario.world.realCluster
	if _, err := activeScenario.realCluster.BuildTUI(activeTest); err != nil {
		return fmt.Errorf("build TUI: %w", err)
	}
	return nil
}

func u21StartEmptyEndpoint() error {
	activeScenario.world = &World{}
	if err := activeScenario.world.StartRealCluster(harness.FaultInjection{NoSessions: true}); err != nil {
		return err
	}
	activeScenario.realCluster = activeScenario.world.realCluster
	if _, err := activeScenario.realCluster.BuildTUI(activeTest); err != nil {
		return fmt.Errorf("build TUI: %w", err)
	}
	return nil
}

func u21RunHumanList() error {
	stdout, stderr, code, runErr := activeScenario.realCluster.RunTUI("list")
	activeScenario.lastBody = []byte(stdout)
	activeScenario.lastStatus = code
	if runErr != nil {
		return fmt.Errorf("run human list: %w; stderr=%s", runErr, stderr)
	}
	return nil
}

func u21AssertEndpointID() error {
	if !strings.Contains(string(activeScenario.lastBody), "endpoint-1") {
		return fmt.Errorf("human list output lacks endpoint id: %s", activeScenario.lastBody)
	}
	return nil
}
