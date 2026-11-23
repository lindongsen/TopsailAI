package bdd

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"
	"time"

	"github.com/cucumber/godog"
	"topsailai_agent_cluster/internal/client"
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
	ctx.Step(`^a credential permitted to clean a workspace$`, grantWorkspaceClean)
	ctx.Step(`^a credential permitted to start a drive$`, grantDriveStart)
	ctx.Step(`^a credential permitted to stop a drive$`, grantDriveStop)
	ctx.Step(`^a credential permitted to resume an agent$`, grantAgentResume)
	ctx.Step(`^a credential permitted to start an agent$`, grantAgentStart)
	ctx.Step(`^a credential permitted to select a model$`, grantModelSelect)
	ctx.Step(`^a credential permitted to execute a command$`, grantCommandExec)
	ctx.Step(`^a credential permitted to register a project$`, grantProjectAdd)
	ctx.Step(`^a credential permitted to remove a project$`, grantProjectRemove)
	ctx.Step(`^a credential permitted to set the machine model$`, grantModelSet)
	ctx.Step(`^a credential permitted only to view$`, grantViewOnly)
	ctx.Step(`^the message send command is submitted with that credential$`, submitMessageSend)
	ctx.Step(`^the context inject command is submitted with that credential$`, submitContextInject)
	ctx.Step(`^the execution interrupt command is submitted with that credential$`, submitExecutionInterrupt)
	ctx.Step(`^the agent stop command is submitted with that credential$`, submitAgentStop)
	ctx.Step(`^the workspace clean command is submitted with that credential$`, submitWorkspaceClean)
	ctx.Step(`^the agent drive start command is submitted with that credential$`, submitDriveStart)
	ctx.Step(`^the agent drive stop command is submitted with that credential$`, submitDriveStop)
	ctx.Step(`^the agent resume command is submitted against the stopped session with that credential$`, submitAgentResume)
	ctx.Step(`^the agent start command is submitted with that credential$`, submitAgentStart)
	ctx.Step(`^the agent model select command is submitted with that credential$`, submitModelSelect)
	ctx.Step(`^the command exec operation is submitted with an allowlisted argv and that credential$`, submitCommandExec)
	ctx.Step(`^the project add command is submitted with that credential$`, submitProjectAdd)
	ctx.Step(`^the project remove command is submitted with that credential$`, submitProjectRemove)
	ctx.Step(`^the agent model set command is submitted with that credential$`, submitModelSet)
	ctx.Step(`^the command is accepted and the provider is invoked once$`, assertAcceptedAndInvokedOnce)
	ctx.Step(`^the command is accepted and the endpoint ran it without the provider$`, assertAcceptedAndRanOnEndpoint)
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
	// Cleanup addresses provider-owned expired artifacts by the exact session
	// mapping rather than a live process generation, so the live row is a valid
	// target and the policy hook is the only remaining reason to refuse.
	protocol.OperationWorkspaceClean:  {Permission: protocol.OperationWorkspaceClean, Target: "fixture-session", Payload: `{}`},
	protocol.OperationAgentDriveStart: {Permission: protocol.OperationAgentDriveStart, Target: "fixture-session", Payload: `{}`},
	protocol.OperationAgentDriveStop:  {Permission: protocol.OperationAgentDriveStop, Target: "fixture-session", Payload: `{}`},
	// Resume addresses the stopped row, because resume authorizes on the absence
	// of a live target: the live row would be refused by target validation before
	// the policy hook ran.
	protocol.OperationAgentResume: {Permission: protocol.OperationAgentResume, Target: "stopped-session", Payload: `{}`},
	// Start carries no target: the Endpoint resolves the adapter from the launch
	// profile, and the profile revision must match the descriptor revision.
	protocol.OperationAgentStart: {Permission: protocol.OperationAgentStart, Target: "", Payload: `{"task":"bdd task"}`, Folder: "/work/bdd-project"},
	// Model select declares operation and payload schema version "1", not "v1".
	protocol.OperationAgentModelSelect: {Permission: protocol.OperationAgentModelSelect, Target: "fixture-session", Payload: `{"model_profile_id":"fixture-model-a"}`, OperationVersion: protocol.ModelSelectPayloadVersion, PayloadSchemaVersion: protocol.ModelSelectPayloadVersion},
	// Command exec declares operation and payload schema version "1", and its argv
	// must be allowlisted: the allowlist runs inside the same policy hook, so a
	// non-allowlisted argv would be reported as policy_denied and the negative
	// scenario would pass for the wrong reason.
	// command.exec runs on the Endpoint, so the argv must name a real executable
	// on PATH. The removed fixture's "fixture-tool" was answered by the provider and
	// never executed; now that the Endpoint starts the process itself, that argv
	// would be refused with command_not_found before the allowlist was consulted.
	protocol.OperationCommandExec: {Permission: protocol.OperationCommandExec, Target: "fixture-session", Payload: `{"argv":["pwd"]}`, OperationVersion: protocol.CommandExecPayloadVersion, PayloadSchemaVersion: protocol.CommandExecPayloadVersion},
	// project.add carries no target, because it creates a resource that does not
	// exist yet and therefore has no identity to address. Its payload is computed
	// at submit time rather than declared here: the folder must sit inside the
	// project root this scenario creates, and a hardcoded path could never satisfy
	// the confinement check, so the refusal would come from confinement instead of
	// from the policy hook the scenario exists to prove.
	protocol.OperationProjectAdd: {Permission: protocol.OperationProjectAdd, Target: ""},
	// project.remove addresses the Cluster-minted project identity, which exists
	// only after a catalog read has minted the durable mapping. Both the target and
	// the opaque provider slot are therefore resolved at submit time, and the kind
	// is declared here because the Endpoint resolves the adapter and the authority
	// check by kind: a session kind would address a process a registry entry does
	// not have.
	protocol.OperationProjectRemove: {Permission: protocol.OperationProjectRemove, Target: "", TargetKind: protocol.ResourceProject},
	// agent.model.set carries no target, because it declares a machine-wide
	// default rather than changing a running process. Its payload is computed at
	// submit time rather than declared here: the identifier must be one this
	// Endpoint minted, and the mapping only exists after a registry read, so a
	// hardcoded profile ID would be refused as unknown before the policy hook and
	// the negative scenario would pass for the wrong reason.
	protocol.OperationAgentModelSet: {Permission: protocol.OperationAgentModelSet, Target: "", OperationVersion: protocol.ModelSetPayloadVersion, PayloadSchemaVersion: protocol.ModelSetPayloadVersion},
}

// permissionMatrixOperation describes one row of the command matrix.
type permissionMatrixOperation struct {
	// Permission is the single operation name the token is granted.
	Permission string
	// Target is the fixture session key the operation addresses, or empty when
	// the operation carries no target.
	Target string
	// TargetKind is the standard resource kind the target addresses. Empty keeps
	// "session", which is what every pre-existing row submits. A project target
	// must state "project", because the Endpoint resolves the adapter and the
	// authority check by kind.
	TargetKind string
	// ProviderTarget is the opaque Provider-owned exact-target evidence the intent
	// carries. It is a separate intent field rather than a payload field, because
	// the adapter decodes the payload strictly. A project.remove row needs it
	// because the Endpoint's durable mapping key is a digest of the folder, so the
	// caller is the only party that still holds the path.
	ProviderTarget string
	// Payload is the JSON document the adapter accepts for this operation.
	Payload string
	// OperationVersion is the version the Endpoint matches against the advertised
	// capability version. Empty means the default "v1".
	OperationVersion string
	// PayloadSchemaVersion is the version the adapter uses to decode the payload.
	// Empty means the default "v1".
	PayloadSchemaVersion string
	// Folder is the launch directory an agent.start carries. It is a separate
	// intent field rather than a payload field, because the adapter decodes the
	// payload strictly and would reject an unknown key before the provider was
	// reached. Empty means the operation carries no folder.
	Folder string
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
var permissionMatrixAllowlist = []string{"pwd"}

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
				// agent.model.set carries its own payload schema version, and the
				// adapter intersects a capability by name AND version. Declaring
				// the operation without its version would advertise it as "v1",
				// so the intersection would drop it and every set command would be
				// refused as unsupported before the policy hook ran. The positive
				// row would then fail for a reason unrelated to authorization.
				protocol.OperationAgentModelSet: protocol.ModelSetPayloadVersion,
			},
			CommandAllowlist: [][]string{permissionMatrixAllowlist},
			// The project root is the only security boundary for project.add, so
			// the positive row needs it: without a configured root the operation
			// fails closed with project_root_unconfigured before the policy hook
			// runs, and the authorization assertion would pass while proving a
			// configuration refusal instead. The harness creates the directory and
			// publishes the same path through the mock catalog, so the folder the
			// positive row registers and the folder the removal row addresses are
			// the one real directory inside the root.
			ProjectRoot: true,
		},
	})
	if err != nil {
		return err
	}
	activeScenario.world.realCluster = cluster
	activeScenario.realCluster = cluster
	// The launch catalog is read with the view credential, which the policy
	// grants launch.query. Reading it with the row token would 403 on every
	// row that does not hold launch.query, and agent.start would then be
	// submitted with a provider key instead of the minted profile identity.
	activeScenario.world.launchProfileToken = permissionMatrixToken(security.ScopeView)
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
func grantWorkspaceClean() error     { return grantPermission(protocol.OperationWorkspaceClean) }
func grantDriveStart() error         { return grantPermission(protocol.OperationAgentDriveStart) }
func grantDriveStop() error          { return grantPermission(protocol.OperationAgentDriveStop) }
func grantAgentResume() error        { return grantPermission(protocol.OperationAgentResume) }
func grantAgentStart() error         { return grantPermission(protocol.OperationAgentStart) }
func grantModelSelect() error        { return grantPermission(protocol.OperationAgentModelSelect) }
func grantCommandExec() error        { return grantPermission(protocol.OperationCommandExec) }
func grantProjectAdd() error         { return grantPermission(protocol.OperationProjectAdd) }
func grantProjectRemove() error      { return grantPermission(protocol.OperationProjectRemove) }
func grantModelSet() error           { return grantPermission(protocol.OperationAgentModelSet) }

// grantViewOnly selects the token that holds an unrelated read scope, so the
// credential is valid and the Endpoint refuses the operation under test for lack
// of authority rather than for lack of a credential.
func grantViewOnly() error {
	return grantPermission(security.ScopeView)
}

// submitPermissionMatrixOperation submits one matrix row with the scenario's
// token and records the provider invocation count before submission.
func submitPermissionMatrixOperation(operation string) error {
	row, ok := permissionMatrixOperations[operation]
	if !ok {
		return fmt.Errorf("operation %q is not part of the permission matrix", operation)
	}
	return submitPermissionMatrixOperationWithPayload(operation, row.Payload)
}

// submitPermissionMatrixOperationWithPayload submits one matrix row with a
// caller-supplied payload, so a row whose payload depends on a Cluster-minted
// identity can still reuse the same invocation accounting and token handling.
func submitPermissionMatrixOperationWithPayload(operation, payload string) error {
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
		TargetKind:           row.TargetKind,
		ProviderTarget:       row.ProviderTarget,
		Payload:              payload,
		OperationVersion:     row.OperationVersion,
		PayloadSchemaVersion: row.PayloadSchemaVersion,
		Folder:               row.Folder,
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
func submitWorkspaceClean() error {
	return submitPermissionMatrixOperation(protocol.OperationWorkspaceClean)
}
func submitDriveStart() error {
	return submitPermissionMatrixOperation(protocol.OperationAgentDriveStart)
}
func submitDriveStop() error {
	return submitPermissionMatrixOperation(protocol.OperationAgentDriveStop)
}
func submitAgentResume() error { return submitPermissionMatrixOperation(protocol.OperationAgentResume) }
func submitAgentStart() error  { return submitPermissionMatrixOperation(protocol.OperationAgentStart) }

// submitModelSelect resolves the Cluster-minted model profile identity before
// submitting, because the payload must carry the identity the adapter minted, not
// the provider key the fixture happens to use. A provider key would be refused by
// the adapter before the provider was reached, so the scenario would pass while
// proving nothing about authorization.
func submitModelSelect() error {
	row, ok := permissionMatrixOperations[protocol.OperationAgentModelSelect]
	if !ok {
		return fmt.Errorf("operation %q is not part of the permission matrix", protocol.OperationAgentModelSelect)
	}
	profileID, err := activeScenario.world.resolveModelProfile(row.Target, "")
	if err != nil {
		return err
	}
	payload, err := json.Marshal(map[string]string{"model_profile_id": profileID})
	if err != nil {
		return err
	}
	return submitPermissionMatrixOperationWithPayload(protocol.OperationAgentModelSelect, string(payload))
}

// matrixProject reads the live project catalog with the view credential and
// returns the Cluster-minted project identity together with the folder the
// Provider reports for it.
//
// The catalog is read with the view token rather than with the row token,
// because each matrix row grants exactly one operation: the project.remove token
// holds project.remove and nothing else, so reading the catalog with it would be
// refused with policy_denied and the scenario would fail before it submitted the
// operation it exists to prove. The view token is a scope grant, and the view
// scope covers project.list.
//
// The identity is read from the live catalog instead of being written into the
// scenario, because a project ID is a Cluster-minted opaque value: hardcoding one
// would assert a mapping detail and would break the moment the mapping changed.
func matrixProject() (string, string, error) {
	if activeScenario.world == nil || activeScenario.world.realCluster == nil {
		return "", "", fmt.Errorf("real cluster is not running")
	}
	api := client.NewAPIClient(activeScenario.realCluster.URL(""), "secret")
	// The harness Server runs in bearer mode, so this in-process client must
	// present the same scheme. An empty mode would fall back to the HMAC default
	// and be refused before the request reached the Endpoint, which is the same
	// reason performQueryRead sets it explicitly.
	api.AuthMode = security.ModeBearer
	api.EndpointTokens = map[string]string{scopedEndpointID: permissionMatrixToken(security.ScopeView)}
	catalog, err := api.GetProjectCatalog(context.Background(), scopedEndpointID)
	if err != nil {
		return "", "", fmt.Errorf("read project catalog: %w", err)
	}
	if len(catalog.Projects) == 0 {
		return "", "", fmt.Errorf("project catalog reported no project, so the registration rows cannot address one")
	}
	project := catalog.Projects[0]
	if project.ProjectID == "" || project.Path == "" {
		return "", "", fmt.Errorf("project catalog row is incomplete: %+v", project)
	}
	return project.ProjectID, project.Path, nil
}

// submitProjectAdd registers the folder the Provider publishes in its catalog.
//
// The folder is taken from the catalog rather than written into the scenario,
// because the Cluster confines a registration to the configured project root and
// the harness creates that root per scenario. A hardcoded path could never sit
// inside it, so the refusal would come from the confinement check instead of the
// policy hook, and the scenario would pass while proving the wrong thing.
func submitProjectAdd() error {
	_, folder, err := matrixProject()
	if err != nil {
		return err
	}
	payload, err := json.Marshal(map[string]string{"folder": folder})
	if err != nil {
		return err
	}
	return submitPermissionMatrixOperationWithPayload(protocol.OperationProjectAdd, string(payload))
}

// submitProjectRemove removes the registry entry for the project the catalog
// reports.
//
// The opaque provider slot carries the folder, because the Endpoint's durable
// mapping key is a digest of that folder and the caller is the only party that
// still holds the path. The Provider binds the slot to the mapping key it was
// given, so a slot naming a different folder is refused rather than applied to
// the wrong entry.
func submitProjectRemove() error {
	projectID, folder, err := matrixProject()
	if err != nil {
		return err
	}
	slot, err := json.Marshal(map[string]string{"project_path": folder})
	if err != nil {
		return err
	}
	row := permissionMatrixOperations[protocol.OperationProjectRemove]
	row.Target = projectID
	row.ProviderTarget = string(slot)
	permissionMatrixOperations[protocol.OperationProjectRemove] = row
	return submitPermissionMatrixOperation(protocol.OperationProjectRemove)
}

// matrixModelProfile reads the live model registry with the view credential and
// returns the Cluster-minted profile identity of its first entry.
//
// The registry is read with the view token rather than with the row token,
// because the row token holds only the control permission and the read would be
// refused. Reading with the row token would make the positive scenario fail for a
// reason unrelated to the operation under test.
//
// The identifier must come from this read rather than from the scenario, because
// the Endpoint refuses a profile it never minted. A hardcoded identifier would be
// refused as unknown_model_profile before the policy hook, so the negative
// scenario would pass while proving nothing about authorization.
func matrixModelProfile() (string, error) {
	if activeScenario.world == nil || activeScenario.world.realCluster == nil {
		return "", fmt.Errorf("real cluster is not running")
	}
	api := client.NewAPIClient(activeScenario.realCluster.URL(""), "secret")
	api.AuthMode = security.ModeBearer
	api.EndpointTokens = map[string]string{scopedEndpointID: permissionMatrixToken(security.ScopeView)}
	registry, err := api.GetModelRegistry(context.Background(), scopedEndpointID)
	if err != nil {
		return "", fmt.Errorf("read model registry: %w", err)
	}
	if len(registry.Entries) == 0 {
		return "", fmt.Errorf("model registry reported no entry, so the set row cannot address one")
	}
	entry := registry.Entries[0]
	if entry.ModelProfileID == "" {
		return "", fmt.Errorf("model registry row is incomplete: %+v", entry)
	}
	return entry.ModelProfileID, nil
}

// submitModelSet declares the machine-wide model using an identifier the
// Endpoint minted.
//
// The payload is computed here rather than declared in the row table, because the
// mapping only exists after a registry read. The row itself carries no target,
// because the operation addresses the machine.
func submitModelSet() error {
	profileID, err := matrixModelProfile()
	if err != nil {
		return err
	}
	payload, err := json.Marshal(map[string]string{"model_profile_id": profileID})
	if err != nil {
		return err
	}
	return submitPermissionMatrixOperationWithPayload(protocol.OperationAgentModelSet, string(payload))
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

// assertAcceptedAndRanOnEndpoint proves the allowed command.exec row ran on the
// Endpoint and did not reach the provider.
//
// The provider invocation count is asserted unchanged rather than incremented,
// because command.exec is Endpoint-native: the Endpoint keeps the allowlist, the
// working directory, the confinement, the minimal environment, the timeout and the
// exact-process cleanup, and it does not start the provider CLI for this operation.
// Asserting an increment here would demand the behaviour the contract forbids.
func assertAcceptedAndRanOnEndpoint() error {
	status, err := activeScenario.world.PollRealCommand(permissionMatrixCommandID, 20*time.Second)
	if err != nil {
		return err
	}
	if code, _ := status["error_code"].(string); code != "" {
		return fmt.Errorf("allowed command ended with error_code=%q status=%v", code, status)
	}
	// Exit confirmation is the evidence that a process really ran and its exit
	// status was observed. A receipt without it would be indistinguishable from a
	// request that was merely accepted.
	confirmed, _ := status["exit_confirmed"].(bool)
	if !confirmed {
		return fmt.Errorf("allowed command was not exit-confirmed, so no process was observed: %v", status)
	}
	after, err := activeScenario.world.ProviderInvocationCount()
	if err != nil {
		return err
	}
	if after != permissionMatrixInvocationsBefore {
		return fmt.Errorf("provider invocations before=%d after=%d, want unchanged because command.exec is endpoint-native", permissionMatrixInvocationsBefore, after)
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
