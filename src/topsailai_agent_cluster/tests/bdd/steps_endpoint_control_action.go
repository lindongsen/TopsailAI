package bdd

import (
	"bufio"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/cucumber/godog"
	"topsailai_agent_cluster/internal/protocol"
	"topsailai_agent_cluster/internal/security"
	"topsailai_agent_cluster/tests/harness"
)

// registerEndpointControlActionSteps registers the provider control family
// scenarios.
//
// The family is tested on its own cluster because the catalog reaches only the
// TopsailAI adapter: the generic fixture adapter is constructed without one, so a
// ctl. operation there is refused as unsupported before the policy hook runs. A
// scenario on that adapter would therefore pass while proving nothing about
// authorization.
func registerEndpointControlActionSteps(ctx *godog.ScenarioContext) {
	ctx.Step(`^a real cluster that publishes a control action catalog$`, startControlActionCluster)
	ctx.Step(`^a credential permitted to invoke the fixture control action$`, grantControlAction)
	ctx.Step(`^a credential permitted only to view the control action$`, grantControlActionViewOnly)
	ctx.Step(`^the fixture control action is submitted with that credential$`, submitControlAction)
	ctx.Step(`^the control action is accepted and the provider is invoked once$`, assertControlActionAccepted)
	ctx.Step(`^the control action is refused with policy denied and the provider is not invoked$`, assertControlActionRefused)
}

// controlActionName is the catalog action under test. It is a name this build
// does not know, which is the point: the catalog is the only source of ctl.
// actions, so the scenario proves the configured entry is what made the operation
// reachable rather than a compiled-in list.
const controlActionName = "fixture_probe"

// controlActionOperation is the standard operation name the catalog entry
// produces. It is derived from the prefix the cluster defines, not spelled out,
// so the scenario cannot drift from the contract.
var controlActionOperation = security.ProviderControlPrefix + controlActionName

// controlActionCatalog is the one real catalog entry the cluster loads.
//
// The command is a provider argv template, so the positive scenario proves the
// whole path from the advertised capability through the policy hook to a real
// provider invocation. The permission is the control scope, which is what the
// shipped catalog uses for mutating actions.
var controlActionCatalog = []harness.ControlAction{{
	Name:       controlActionName,
	Permission: security.ScopeControl,
	Command:    []string{"runtime", "control", controlActionName, "-s", "{session}", "--json"},
}}

// controlActionToken and controlActionViewToken are the two credentials the
// scenarios present. One holds exactly the configured action, the other holds an
// unrelated read scope, so a refusal cannot be explained by a missing credential.
const (
	controlActionToken     = "bdd-control-action-token"
	controlActionViewToken = "bdd-control-action-view-token"
)

// controlActionInvocationLog is the per-scenario path the TopsailAI fixture
// appends its argv records to.
var controlActionInvocationLog string

// controlActionGranted is the token the current scenario presents.
var controlActionGranted string

// controlActionCommandID carries the submitted command between steps.
var controlActionCommandID string

// startControlActionCluster starts one real cluster whose TopsailAI adapter loads
// a catalog with one action, and whose policy directory already contains both
// credentials.
//
// The policy files are written before the Endpoint starts, because the Endpoint
// reads its policy directory at startup and the harness captures the Endpoint
// environment at that moment. Appending afterwards would leave the running
// process permissive and every negative scenario would pass while proving
// nothing.
func startControlActionCluster() error {
	if activeTest == nil {
		return fmt.Errorf("active BDD test is not initialized")
	}
	if activeScenario.world == nil {
		activeScenario.world = &World{}
	}
	controlActionGranted = ""
	controlActionCommandID = ""
	controlActionInvocationLog = filepath.Join(activeTest.TempDir(), "control-action-invocations.jsonl")
	policyDir, err := writeAccessPolicyGrants([]accessPolicyGrant{
		// The positive credential holds the exact configured operation. It is a
		// permission rather than the control scope because the control scope
		// covers every ctl. action, so a scenario that granted it could not show
		// that this action is what the policy checked.
		{Token: controlActionToken, Permissions: []string{controlActionOperation}},
		// The negative credential is valid and holds an unrelated read scope, so
		// the Endpoint refuses for lack of authority rather than for lack of a
		// credential.
		{Token: controlActionViewToken, Scopes: []string{security.ScopeView}},
	})
	if err != nil {
		return err
	}
	cluster, err := harness.StartCluster(activeTest, harness.ClusterOptions{
		ProviderType:        "topsailai",
		EndpointEnvironment: map[string]string{"AGENT_CLUSTER_ENDPOINT_ACCESS_POLICY_DIR": policyDir},
		Faults: harness.FaultInjection{
			ControlActions:        controlActionCatalog,
			ProviderInvocationLog: controlActionInvocationLog,
		},
	})
	if err != nil {
		return err
	}
	activeScenario.world.realCluster = cluster
	activeScenario.realCluster = cluster
	return nil
}

// grantControlAction selects the credential that holds the configured action.
func grantControlAction() error {
	if activeScenario.realCluster == nil {
		return fmt.Errorf("real cluster is not running")
	}
	controlActionGranted = controlActionToken
	return nil
}

// grantControlActionViewOnly selects the credential that holds an unrelated read
// scope.
func grantControlActionViewOnly() error {
	if activeScenario.realCluster == nil {
		return fmt.Errorf("real cluster is not running")
	}
	controlActionGranted = controlActionViewToken
	return nil
}

// submitControlAction submits the configured action against the live session.
//
// The target is the live row because a ctl. operation addresses a running
// session: the Endpoint revalidates the generation before the policy hook runs,
// so an unverified target would be refused by target validation and the scenario
// would prove nothing about authorization.
func submitControlAction() error {
	if activeScenario.world == nil || activeScenario.world.realCluster == nil {
		return fmt.Errorf("real cluster is not running")
	}
	commandID, err := activeScenario.world.SubmitRealCommandWithToken(commandSubmission{
		Operation:     controlActionOperation,
		Target:        "fixture-session",
		Payload:       `{}`,
		EndpointToken: controlActionGranted,
	})
	if err != nil {
		return err
	}
	controlActionCommandID = commandID
	return nil
}

// assertControlActionAccepted proves the allowed action reached the provider
// exactly once and did not end in a refusal that merely looks like success.
func assertControlActionAccepted() error {
	status, err := activeScenario.world.PollRealCommand(controlActionCommandID, 20*time.Second)
	if err != nil {
		return err
	}
	if code, _ := status["error_code"].(string); code != "" {
		return fmt.Errorf("allowed control action ended with error_code=%q status=%v", code, status)
	}
	invocations, err := controlActionInvocations()
	if err != nil {
		return err
	}
	if len(invocations) != 1 {
		return fmt.Errorf("the provider received %d control action invocations, want exactly one; recorded=%v", len(invocations), invocations)
	}
	return nil
}

// assertControlActionRefused proves the denied action ended with policy_denied
// and never reached the provider.
//
// The assertion names the code rather than accepting any refusal, because the
// Endpoint reports several different refusals for this operation: an action
// absent from the catalog is control_action_unconfigured, an unadvertised
// capability is unsupported, and an unknown target is target_not_found. All of
// them also reach the provider zero times, so only the code distinguishes a
// policy decision from a configuration accident.
func assertControlActionRefused() error {
	status, err := activeScenario.world.PollRealCommand(controlActionCommandID, 20*time.Second)
	if err != nil {
		return err
	}
	code, _ := status["error_code"].(string)
	if code != protocol.PolicyDenied {
		return fmt.Errorf("error_code=%q status=%v, want %q", code, status, protocol.PolicyDenied)
	}
	invocations, err := controlActionInvocations()
	if err != nil {
		return err
	}
	if len(invocations) != 0 {
		return fmt.Errorf("a credential without the action reached the provider; recorded=%v", invocations)
	}
	return nil
}

// controlActionInvocations returns the recorded argv arrays that carry the
// configured action.
//
// The filter is required because the TopsailAI fixture records every invocation
// it answers, including a model catalog read, and its record carries only the
// argv. Counting all records would let an unrelated read satisfy "exactly one
// invocation" and would let an unrelated read break "no invocation".
func controlActionInvocations() ([][]string, error) {
	if controlActionInvocationLog == "" {
		return nil, fmt.Errorf("the control action invocation log path was never assigned")
	}
	file, err := os.Open(controlActionInvocationLog)
	if err != nil {
		if os.IsNotExist(err) {
			return nil, nil
		}
		return nil, fmt.Errorf("open control action invocation log: %w", err)
	}
	defer func() { _ = file.Close() }()
	var matched [][]string
	scanner := bufio.NewScanner(file)
	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		if line == "" {
			continue
		}
		var record struct {
			Argv []string `json:"argv"`
		}
		if err := json.Unmarshal([]byte(line), &record); err != nil {
			return nil, fmt.Errorf("decode control action invocation record %q: %w", line, err)
		}
		if containsArg(record.Argv, controlActionName) {
			matched = append(matched, record.Argv)
		}
	}
	if err := scanner.Err(); err != nil {
		return nil, fmt.Errorf("read control action invocation log: %w", err)
	}
	return matched, nil
}
