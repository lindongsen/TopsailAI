package bdd

import (
	"encoding/json"
	"fmt"
	"strconv"
	"strings"

	"github.com/cucumber/godog"
	"topsailai_agent_cluster/internal/protocol"
	"topsailai_agent_cluster/tests/harness"
)

// registerModelSteps registers the model catalog scenarios. They drive the real
// binaries over a real WebSocket, because the row-number rule is a client-side
// decision: only the shipped CLI can prove that a number is resolved against the
// catalog it rendered and never travels to the provider.
func registerModelSteps(ctx *godog.ScenarioContext) {
	ctx.Step(`^a real cluster with a healthy provider for the model catalog$`, startModelCluster)
	ctx.Step(`^a real cluster whose credential may only view and whose provider answers the model catalog$`, startViewModelCluster)
	ctx.Step(`^the model command is run in session scope$`, runModelListInSessionScope)
	ctx.Step(`^the model command is run in workspace scope for the fixture session$`, runModelListInWorkspaceScope)
	ctx.Step(`^the model catalog is rendered with numbered rows$`, assertModelCatalogRendered)
	ctx.Step(`^the second model row is applied in session scope$`, applySecondModelRowInSessionScope)
	ctx.Step(`^the first model row is applied in workspace scope$`, applyFirstModelRowInWorkspaceScope)
	ctx.Step(`^the provider receives the second profile name and no row number$`, assertProviderReceivedSecondProfileName)
	ctx.Step(`^the provider receives the first profile name$`, assertProviderReceivedFirstProfileName)
	ctx.Step(`^the model change is refused for lack of control permission$`, assertModelSelectRefusedForScope)
}

// modelListScript navigates to the sole session and lists the catalog. Two
// navigations are required: model reads the endpoint and the session from the
// current scope, and both are empty at workspace scope.
const modelListScript = "cd 1\ncd 1\nmodel\nquit\n"

// modelSelectScript lists the catalog and then applies the second row. The
// catalog must be rendered in the same session, because a number is resolved
// against the catalog the operator last saw.
const modelSelectScript = "cd 1\ncd 1\nmodel\nmodel 2\ny\nquit\n"

// modelWorkspaceListScript names the session explicitly, because workspace scope
// does not already name a target.
const modelWorkspaceListScript = "model fixture-session\nquit\n"

// modelWorkspaceSelectScript lists the catalog and applies the first row from
// workspace scope, where the session has to be named on both commands.
const modelWorkspaceSelectScript = "model fixture-session\nmodel fixture-session 1\ny\nquit\n"

// startModelCluster starts a real cluster whose adapter can answer a catalog
// request. The generic fixture adapter cannot, so the TopsailAI adapter is
// selected explicitly.
func startModelCluster() error {
	return startModelClusterWithScopes(nil)
}

// startViewModelCluster starts the same cluster with a credential that may only
// view. The catalog read needs view, so it still succeeds; the select needs
// control, so it must be refused.
func startViewModelCluster() error {
	return startModelClusterWithScopes([]string{"view"})
}

// startModelClusterWithScopes starts one real cluster.
//
// The invocation evidence is read from the cluster's own provider record file,
// which the harness passes to the mock as --record-file. A fixture-only argv log
// would never be written: the Generic CLI Adapter starts the provider with exactly
// the environment its configuration names, so a variable set on the Endpoint never
// reaches the provider child.
func startModelClusterWithScopes(scopes []string) error {
	if activeTest == nil {
		return fmt.Errorf("active BDD test is not initialized")
	}
	if activeScenario.world == nil {
		activeScenario.world = &World{}
	}
	options := harness.ClusterOptions{}
	if len(scopes) > 0 {
		// The restriction is written on the Endpoint, because the Endpoint is the
		// only component that decides whether a caller may exercise an operation.
		// The Server forwards every request and holds no authority to refuse one.
		token := scopedTokenName(scopes)
		policyDir, err := writeAccessPolicyDir(map[string][]string{token: scopes})
		if err != nil {
			return err
		}
		options.EndpointEnvironment = map[string]string{"AGENT_CLUSTER_ENDPOINT_ACCESS_POLICY_DIR": policyDir}
		options.CLIEnvironment = map[string]string{"AGENT_CLUSTER_CLI_ENDPOINT_TOKENS": scopedEndpointTokenMap(token)}
	}
	cluster, err := harness.StartCluster(activeTest, options)
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

// runModelListInSessionScope lists the catalog from session scope.
func runModelListInSessionScope() error {
	return runModelScript(modelListScript)
}

// runModelListInWorkspaceScope lists the catalog from workspace scope, naming the
// session explicitly.
func runModelListInWorkspaceScope() error {
	return runModelScript(modelWorkspaceListScript)
}

// applySecondModelRowInSessionScope applies row 2 from session scope.
func applySecondModelRowInSessionScope() error {
	return runModelScript(modelSelectScript)
}

// applyFirstModelRowInWorkspaceScope applies row 1 from workspace scope.
func applyFirstModelRowInWorkspaceScope() error {
	return runModelScript(modelWorkspaceSelectScript)
}

// runModelScript drives one REPL session and records its output.
//
// A non-zero exit is not treated as a failure here, because a refused command is
// reported inside the REPL and the REPL still exits cleanly. The refusal scenario
// asserts on the text instead, so this helper must not pre-empt it.
func runModelScript(script string) error {
	if activeScenario.realCluster == nil {
		return fmt.Errorf("real cluster is not running")
	}
	stdout, stderr, code, err := activeScenario.realCluster.RunTUIInteractive(script, "--wait-timeout-ms", "3000")
	activeScenario.lastBody = []byte(stdout)
	activeScenario.lastStatus = code
	if err != nil && code == 0 {
		return fmt.Errorf("run interactive REPL: %v; stderr=%s", err, stderr)
	}
	if code != 0 {
		return fmt.Errorf("interactive REPL exit code=%d stderr=%s output=%s", code, stderr, stdout)
	}
	return nil
}

// assertModelCatalogRendered proves the catalog was rendered as a numbered table
// with both fixture profiles, instead of an empty answer or a rendering fault.
func assertModelCatalogRendered() error {
	text := interactiveOutput()
	if strings.Contains(text, "offers no selectable model profile") {
		return fmt.Errorf("the catalog was reported as empty, so the fixture did not answer models list: %s", text)
	}
	if strings.Contains(text, "model profiles are unavailable") {
		return fmt.Errorf("the shipped binary does not wire the catalog client: %s", text)
	}
	for _, header := range []string{"NO", "MODEL"} {
		if !strings.Contains(text, header) {
			return fmt.Errorf("the catalog table is missing the %q column: %s", header, text)
		}
	}
	for _, name := range []string{"fixture-model-a", "fixture-model-b"} {
		if !strings.Contains(text, name) {
			return fmt.Errorf("the catalog table is missing profile %q: %s", name, text)
		}
	}
	return nil
}

// modelSelectPayloadKey returns the provider-private model key the adapter sent
// with a model select.
//
// The key is not a top-level argv element: the Generic CLI Adapter sends the typed
// payload on stdin, and the mock records that payload verbatim. Reading the
// recorded payload is therefore the only way to prove which profile reached the
// provider, and it is also where a leaked row number would appear.
func modelSelectPayloadKey(record map[string]any) (string, error) {
	raw, _ := record["payload"].(string)
	if raw == "" {
		return "", fmt.Errorf("the invocation record carries no payload; record=%v", record)
	}
	var payload struct {
		ProviderResourceKey string `json:"provider_resource_key"`
	}
	if err := json.Unmarshal([]byte(raw), &payload); err != nil {
		return "", fmt.Errorf("decode the model select payload %q: %w", raw, err)
	}
	if payload.ProviderResourceKey == "" {
		return "", fmt.Errorf("the model select payload carries no provider_resource_key; payload=%q", raw)
	}
	return payload.ProviderResourceKey, nil
}

// assertProviderReceivedSecondProfileName proves the resolved profile name reached
// the provider and that the row number did not.
func assertProviderReceivedSecondProfileName() error {
	return assertProviderReceivedProfileName("fixture-model-b", "second")
}

// assertProviderReceivedFirstProfileName proves the first profile name reached the
// provider from workspace scope.
func assertProviderReceivedFirstProfileName() error {
	return assertProviderReceivedProfileName("fixture-model-a", "first")
}

// assertProviderReceivedProfileName checks the last model select invocation for one
// expected profile name.
//
// The name travels inside the -a payload, so the payload is what proves a name was
// sent. A leaked row number would appear as that payload's first argument, which is
// exactly what the numeric check rejects.
func assertProviderReceivedProfileName(expected, ordinal string) error {
	records, err := readModelInvocations()
	if err != nil {
		return err
	}
	selects := selectInvocations(records)
	if len(selects) == 0 {
		return fmt.Errorf("the provider received no model select invocation; recorded=%v", records)
	}
	last := selects[len(selects)-1]
	key, err := modelSelectPayloadKey(last)
	if err != nil {
		return err
	}
	if key != expected {
		return fmt.Errorf("the provider did not receive the %s profile name %q; payload key=%q record=%v", ordinal, expected, key, last)
	}
	if _, err := strconv.Atoi(key); err == nil {
		return fmt.Errorf("the row number travelled to the provider instead of being resolved in the client; payload key=%q", key)
	}
	return nil
}

// assertModelSelectRefusedForScope proves a view-only credential can list the
// catalog but cannot change the model.
//
// The assertion is the Endpoint's own refusal code, because the Endpoint is the
// component that decides. A Server-side status would only show that the request
// was forwarded, and the Endpoint reports this refusal inside the durable receipt
// rather than as a transport failure.
//
// What must not happen is a select invocation reaching the provider, because that
// would mean the policy was bypassed.
func assertModelSelectRefusedForScope() error {
	text := interactiveOutput()
	if !strings.Contains(text, protocol.PolicyDenied) {
		return fmt.Errorf("the refusal does not report the %q code: %s", protocol.PolicyDenied, text)
	}
	records, err := readModelInvocations()
	if err != nil {
		return err
	}
	if selects := selectInvocations(records); len(selects) > 0 {
		return fmt.Errorf("a view-only credential reached the provider with a model select; argv=%v", selects)
	}
	return nil
}

// readModelInvocations reads the provider invocation records the mock appended.
//
// The records come from the cluster's own record file rather than from a
// fixture-only argv log, because the record file is the channel the harness
// actually controls: the Generic CLI Adapter starts the provider with exactly the
// environment its configuration names, so a variable set on the Endpoint never
// reaches the provider child.
func readModelInvocations() ([]map[string]any, error) {
	if activeScenario.realCluster == nil {
		return nil, fmt.Errorf("real cluster is not running")
	}
	return activeScenario.realCluster.ProviderInvocationsE()
}

// selectInvocations keeps only the records that carry a model select.
//
// The filter is the recorded operation name, because the mock writes it for every
// invocation. Counting every record would let an unrelated read satisfy "the
// provider received a select" and would let an unrelated read break "no select
// reached the provider".
func selectInvocations(records []map[string]any) []map[string]any {
	selects := make([]map[string]any, 0, len(records))
	for _, record := range records {
		if operation, _ := record["operation"].(string); operation == protocol.OperationAgentModelSelect {
			selects = append(selects, record)
		}
	}
	return selects
}
