package bdd

import (
	"fmt"
	"strings"
	"time"

	"github.com/cucumber/godog"
	"topsailai_agent_cluster/internal/protocol"
	"topsailai_agent_cluster/internal/security"
	"topsailai_agent_cluster/tests/harness"
)

// registerEndpointPermissionMatrixSteps registers the command authorization
// scenarios.
//
// These scenarios exist because a refusal is easy to fake. The Endpoint refuses a
// command for many reasons before it consults the policy: an unknown target, an
// unadvertised capability, a mismatched profile revision, a live target where a
// resume was requested, or a missing generation. Every one of those refusals also
// reaches the provider zero times, so a scenario that only asserted "refused and
// no provider call" would pass while proving nothing about authorization. Each
// scenario therefore declares the capability, the target and the payload the
// operation needs, so the policy is the only remaining reason to refuse.
func registerEndpointPermissionMatrixSteps(ctx *godog.ScenarioContext) {
	ctx.Step(`^a real cluster that publishes a live and a stopped session$`, startPermissionMatrixCluster)
	ctx.Step(`^a credential permitted to send a message$`, grantSendMessage)
	ctx.Step(`^a credential permitted to inject context$`, grantContextInject)
	ctx.Step(`^a credential permitted to interrupt execution$`, grantExecutionInterrupt)
	ctx.Step(`^a credential permitted to stop an agent$`, grantAgentStop)
	ctx.Step(`^a credential permitted to start a drive$`, grantDriveStart)
	ctx.Step(`^a credential permitted to stop a drive$`, grantDriveStop)
	ctx.Step(`^a credential permitted to resume an agent$`, grantAgentResume)
	ctx.Step(`^a credential permitted to start an agent$`, grantAgentStart)
	ctx.Step(`^a credential permitted to select a model$`, grantModelSelect)
	ctx.Step(`^a credential permitted to execute a command$`, grantCommandExec)
	ctx.Step(`^a credential permitted only to view$`, grantViewOnly)
	ctx.Step(`^the message send command is submitted with that credential$`, submitMessageSend)
	ctx.Step(`^the context inject command is submitted with that credential$`, submitContextInject)
	ctx.Step(`^the execution interrupt command is submitted with that credential$`, submitExecutionInterrupt)
	ctx.Step(`^the agent stop command is submitted with that credential$`, submitAgentStop)
	ctx.Step(`^the agent drive start command is submitted with that credential$`, submitDriveStart)
	ctx.Step(`^the agent drive stop command is submitted with that credential$`, submitDriveStop)
	ctx.Step(`^the agent resume command is submitted against the stopped session with that credential$`, submitAgentResume)
	ctx.Step(`^the agent start command is submitted with that credential$`, submitAgentStart)
	ctx.Step(`^the agent model select command is submitted with that credential$`, submitModelSelect)
	ctx.Step(`^the command exec operation is submitted with an allowlisted argv and that credential$`, submitCommandExec)
	ctx.Step(`^the command is accepted and the provider is invoked once$`, assertAcceptedAndInvokedOnce)
	ctx.Step(`^the command is refused with policy denied and the provider is not invoked$`, assertRefusedWithoutInvocation)
}

// permissionMatrixOperations is the fixture-adapter half of the command matrix.
//
// Each entry names the operation, the permission that grants it, the target the
// operation needs, and the payload the adapter accepts. The table exists so one
// cluster serves every row: starting a cluster per operation would multiply the
// suite runtime for no extra evidence, and the rows are independent because each
// uses its own token.
var permissionMatrixOperations = map[string]permissionMatrixOperation{
	protocol.OperationMessageSend:        {Permission: protocol.OperationMessageSend, Target: "fixture-session", Payload: `{"text":"hello"}`},
	protocol.OperationContextInject:      {Permission: protocol.OperationContextInject, Target: "fixture-session", Payload: `{"text":"context"}`},
	protocol.OperationExecutionInterrupt: {Permission: protocol.OperationExecutionInterrupt, Target: "fixture-session", Payload: `{}`},
	protocol.OperationAgentStop:          {Permission: protocol.OperationAgentStop, Target: "fixture-session", Payload: `{}`},
	protocol.OperationAgentDriveStart:    {Permission: protocol.OperationAgentDriveStart, Target: "fixture-session", Payload: `{}`},
	protocol.OperationAgentDriveStop:     {Permission: protocol.OperationAgentDriveStop, Target: "fixture-session", Payload: `{}`},
	// Resume addresses the stopped row, because resume authorizes on the absence
	// of a live target: the live row would be refused by target validation before
	// the policy hook ran.
	protocol.OperationAgentResume: {Permission: protocol.OperationAgentResume, Target: "stopped-session", Payload: `{}`},
	// Start carries no target: the Endpoint resolves the adapter from the launch
	// profile, and the profile revision must match the descriptor revision.
	protocol.OperationAgentStart: {Permission: protocol.OperationAgentStart, Target: "", Payload: `{"task":"bdd task"}`},
	// Model select declares operation and payload schema version "1", not "v1".
	protocol.OperationAgentModelSelect: {Permission: protocol.OperationAgentModelSelect, Target: "fixture-session", Payload: `{"model_profile_id":"fixture-model-a"}`, OperationVersion: protocol.ModelSelectPayloadVersion, PayloadSchemaVersion: protocol.ModelSelectPayloadVersion},
	// Command exec declares operation and payload schema version "1", and its argv
	// must be allowlisted: the allowlist runs inside the same policy hook, so a
	// non-allowlisted argv would be reported as policy_denied and the negative
	// scenario would pass for the wrong reason.
	protocol.OperationCommandExec: {Permission: protocol.OperationCommandExec, Target: "fixture-session", Payload: `{"argv":["fixture-tool","status"]}`, OperationVersion: protocol.CommandExecPayloadVersion, PayloadSchemaVersion: protocol.CommandExecPayloadVersion},
}

// permissionMatrixOperation describes one row of the command matrix.
type permissionMatrixOperation struct {
	// Permission is the single operation name the token is granted.
	Permission string
	// Target is the fixture session key the operation addresses, or empty when
	// the operation carries no target.
	Target string
	// Payload is the JSON document the adapter accepts for this operation.
	Payload string
	// OperationVersion is the version the Endpoint matches against the advertised
	// capability version. Empty means the default "v1".
	OperationVersion string
	// PayloadSchemaVersion is the version the adapter uses to decode the payload.
	// Empty means the default "v1".
	PayloadSchemaVersion string
}

// permissionMatrixToken derives a token name from the granted permission, so two
// rows never share a credential and a leaked token cannot satisfy another row.
func permissionMatrixToken(permission string) string {
	return "bdd-permission-" + strings.ReplaceAll(permission, ".", "-") + "-token"
}

// permissionMatrixGranted is the permission the current scenario's token holds.
var permissionMatrixGranted string

// permissionMatrixAllowlist is the argv prefix the Endpoint accepts for
// command.exec. It is deliberately the same argv the positive and negative
// command.exec rows submit, so the allowlist can never be the reason a negative
// row was refused.
var permissionMatrixAllowlist = []string{"fixture-tool", "status"}

// startPermissionMatrixCluster starts one real cluster that publishes both a live
// and a stopped session, advertises every operation under test, accepts the
// command.exec argv the matrix submits, and reads a policy directory that already
// contains every token the matrix uses.
//
// The policy files are written before the Endpoint starts, because the Endpoint
// reads its policy directory at startup and the harness captures the Endpoint
// environment at that moment. Appending to the environment afterwards would leave
// the running process permissive, and every negative scenario would then pass
// while proving nothing.
func startPermissionMatrixCluster() error {
	if activeTest == nil {
		return fmt.Errorf("active BDD test is not initialized")
	}
	if activeScenario.world == nil {
		activeScenario.world = &World{}
	}
	permissionMatrixGranted = ""
	operations := make([]string, 0, len(permissionMatrixOperations))
	for operation := range permissionMatrixOperations {
		operations = append(operations, operation)
	}
	policyDir, err := writePermissionMatrixPolicy()
	if err != nil {
		return err
	}
	cluster, err := harness.StartCluster(activeTest, harness.ClusterOptions{
		EndpointEnvironment: map[string]string{"AGENT_CLUSTER_ENDPOINT_ACCESS_POLICY_DIR": policyDir},
		Faults: harness.FaultInjection{
			FixtureMode:            "mixed",
			CapabilityRevision:     "v1",
			AdvertisedCapabilities: operations,
			CapabilityVersions: map[string]string{
				protocol.OperationCommandExec:      protocol.CommandExecPayloadVersion,
				protocol.OperationAgentModelSelect: protocol.ModelSelectPayloadVersion,
			},
			CommandAllowlist: [][]string{permissionMatrixAllowlist},
		},
	})
	if err != nil {
		return err
	}
	activeScenario.world.realCluster = cluster
	activeScenario.realCluster = cluster
	return nil
}

// writePermissionMatrixPolicy writes one policy file per matrix row plus the
// unrelated-grant token, and returns the directory path.
//
// Each row gets its own token granting exactly one operation, so a scenario can
// never be satisfied by authority granted for a different row. The grant is a
// permission rather than a scope because a scope is a bundle: the control scope
// covers every mutating operation, so a scenario that granted it could not show
// that the operation under test is what the policy checked.
func writePermissionMatrixPolicy() (string, error) {
	grants := make([]accessPolicyGrant, 0, len(permissionMatrixOperations)+1)
	for operation := range permissionMatrixOperations {
		grants = append(grants, accessPolicyGrant{Token: permissionMatrixToken(operation), Permissions: []string{operation}})
	}
	// The unrelated grant is a scope, not a permission: view is a scope name and
	// not an operation name, so declaring it as a permission would load with a
	// warning and grant nothing, and the negative scenarios would then be refused
	// for holding no authority at all rather than for lacking the operation.
	grants = append(grants, accessPolicyGrant{Token: permissionMatrixToken(security.ScopeView), Scopes: []string{security.ScopeView}})
	return writeAccessPolicyGrants(grants)
}

// grantPermission selects the token that holds exactly one operation.
func grantPermission(permission string) error {
	if activeScenario.realCluster == nil {
		return fmt.Errorf("real cluster is not running")
	}
	permissionMatrixGranted = permissionMatrixToken(permission)
	return nil
}

func grantSendMessage() error        { return grantPermission(protocol.OperationMessageSend) }
func grantContextInject() error      { return grantPermission(protocol.OperationContextInject) }
func grantExecutionInterrupt() error { return grantPermission(protocol.OperationExecutionInterrupt) }
func grantAgentStop() error          { return grantPermission(protocol.OperationAgentStop) }
func grantDriveStart() error         { return grantPermission(protocol.OperationAgentDriveStart) }
func grantDriveStop() error          { return grantPermission(protocol.OperationAgentDriveStop) }
func grantAgentResume() error        { return grantPermission(protocol.OperationAgentResume) }
func grantAgentStart() error         { return grantPermission(protocol.OperationAgentStart) }
func grantModelSelect() error        { return grantPermission(protocol.OperationAgentModelSelect) }
func grantCommandExec() error        { return grantPermission(protocol.OperationCommandExec) }

// grantViewOnly selects the token that holds an unrelated read scope, so the
// credential is valid and the Endpoint refuses the operation under test for lack
// of authority rather than for lack of a credential.
func grantViewOnly() error {
	return grantPermission(security.ScopeView)
}

// submitPermissionMatrixOperation submits one matrix row with the scenario's
// token and records the provider invocation count before submission.
func submitPermissionMatrixOperation(operation string) error {
	if activeScenario.world == nil || activeScenario.world.realCluster == nil {
		return fmt.Errorf("real cluster is not running")
	}
	row, ok := permissionMatrixOperations[operation]
	if !ok {
		return fmt.Errorf("operation %q is not part of the permission matrix", operation)
	}
	before, err := activeScenario.world.ProviderInvocationCount()
	if err != nil {
		return err
	}
	permissionMatrixInvocationsBefore = before
	commandID, err := activeScenario.world.SubmitRealCommandWithToken(commandSubmission{
		Operation:            operation,
		Target:               row.Target,
		Payload:              row.Payload,
		OperationVersion:     row.OperationVersion,
		PayloadSchemaVersion: row.PayloadSchemaVersion,
		EndpointToken:        permissionMatrixGranted,
	})
	if err != nil {
		return err
	}
	permissionMatrixCommandID = commandID
	return nil
}

// permissionMatrixInvocationsBefore and permissionMatrixCommandID carry the
// per-scenario evidence between the submit and assert steps.
var (
	permissionMatrixInvocationsBefore int
	permissionMatrixCommandID         string
)

func submitMessageSend() error { return submitPermissionMatrixOperation(protocol.OperationMessageSend) }
func submitContextInject() error {
	return submitPermissionMatrixOperation(protocol.OperationContextInject)
}
func submitExecutionInterrupt() error {
	return submitPermissionMatrixOperation(protocol.OperationExecutionInterrupt)
}
func submitAgentStop() error { return submitPermissionMatrixOperation(protocol.OperationAgentStop) }
func submitDriveStart() error {
	return submitPermissionMatrixOperation(protocol.OperationAgentDriveStart)
}
func submitDriveStop() error {
	return submitPermissionMatrixOperation(protocol.OperationAgentDriveStop)
}
func submitAgentResume() error { return submitPermissionMatrixOperation(protocol.OperationAgentResume) }
func submitAgentStart() error  { return submitPermissionMatrixOperation(protocol.OperationAgentStart) }
func submitModelSelect() error {
	return submitPermissionMatrixOperation(protocol.OperationAgentModelSelect)
}
func submitCommandExec() error { return submitPermissionMatrixOperation(protocol.OperationCommandExec) }

// assertAcceptedAndInvokedOnce proves the allowed request reached the provider
// exactly once and did not end in a refusal that merely looks like success.
func assertAcceptedAndInvokedOnce() error {
	status, err := activeScenario.world.PollRealCommand(permissionMatrixCommandID, 20*time.Second)
	if err != nil {
		return err
	}
	if code, _ := status["error_code"].(string); code != "" {
		return fmt.Errorf("allowed command ended with error_code=%q status=%v", code, status)
	}
	after, err := activeScenario.world.ProviderInvocationCount()
	if err != nil {
		return err
	}
	if after != permissionMatrixInvocationsBefore+1 {
		return fmt.Errorf("provider invocations before=%d after=%d, want exactly one more", permissionMatrixInvocationsBefore, after)
	}
	return nil
}

// assertRefusedWithoutInvocation proves the denied request ended with
// policy_denied and never reached the provider.
func assertRefusedWithoutInvocation() error {
	status, err := activeScenario.world.PollRealCommand(permissionMatrixCommandID, 20*time.Second)
	if err != nil {
		return err
	}
	code, _ := status["error_code"].(string)
	if code != protocol.PolicyDenied {
		return fmt.Errorf("error_code=%q status=%v, want %q", code, status, protocol.PolicyDenied)
	}
	after, err := activeScenario.world.ProviderInvocationCount()
	if err != nil {
		return err
	}
	if after != permissionMatrixInvocationsBefore {
		return fmt.Errorf("provider invocations before=%d after=%d, want unchanged", permissionMatrixInvocationsBefore, after)
	}
	return nil
}
