package bdd

import (
	"bufio"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
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

// modelInvocationLog is the path the fixture appends its argv records to. It is
// assigned by the start step of every scenario, so it never leaks between them.
//
// The path is allocated from the test's own temporary directory rather than from
// the cluster root, because the cluster root only exists after StartCluster has
// returned and the fixture needs the path before it is launched.
var modelInvocationLog string

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

// startModelClusterWithScopes starts one real cluster and points the fixture at a
// per-scenario invocation log.
//
// The invocation log travels through Faults rather than Environment because
// Environment is applied to the Server, while the provider child is spawned by the
// Endpoint. Setting it on the wrong process would leave the log empty and make a
// "no invocation recorded" assertion pass for the wrong reason.
func startModelClusterWithScopes(scopes []string) error {
	if activeTest == nil {
		return fmt.Errorf("active BDD test is not initialized")
	}
	if activeScenario.world == nil {
		activeScenario.world = &World{}
	}
	modelInvocationLog = filepath.Join(activeTest.TempDir(), "model-invocations.jsonl")
	options := harness.ClusterOptions{
		ProviderType: "topsailai",
		Faults:       harness.FaultInjection{ProviderInvocationLog: modelInvocationLog},
	}
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
		options.CLIEnvironment = map[string]string{"AGENT_CLUSTER_ENDPOINT_TOKENS": scopedEndpointTokenMap(token)}
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

// modelSelectPayloadArgs returns the args array of the -a payload the adapter sent
// with a model select.
//
// The profile name is not a top-level argv element: the adapter passes the session
// key to -s and the model instruction to -a, so the name lives inside that JSON
// document. Reading the payload is therefore the only way to prove which profile
// reached the provider, and it is also where a leaked row number would appear.
func modelSelectPayloadArgs(argv []string) ([]string, error) {
	for index := 0; index < len(argv); index++ {
		if argv[index] != "-a" {
			continue
		}
		if index+1 >= len(argv) {
			return nil, fmt.Errorf("the -a flag carries no payload; argv=%v", argv)
		}
		var payload struct {
			Instruction string   `json:"instruction"`
			Args        []string `json:"args"`
		}
		if err := json.Unmarshal([]byte(argv[index+1]), &payload); err != nil {
			return nil, fmt.Errorf("decode the -a payload %q: %w", argv[index+1], err)
		}
		if payload.Instruction != "agent.models" {
			return nil, fmt.Errorf("the -a payload carries instruction %q, not agent.models; argv=%v", payload.Instruction, argv)
		}
		return payload.Args, nil
	}
	return nil, fmt.Errorf("the invocation carries no -a payload; argv=%v", argv)
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
	args, err := modelSelectPayloadArgs(last)
	if err != nil {
		return err
	}
	if len(args) == 0 {
		return fmt.Errorf("the -a payload carries no model argument; argv=%v", last)
	}
	if args[0] != expected {
		return fmt.Errorf("the provider did not receive the %s profile name %q; payload args=%v argv=%v", ordinal, expected, args, last)
	}
	if _, err := strconv.Atoi(args[0]); err == nil {
		return fmt.Errorf("the row number travelled to the provider instead of being resolved in the client; payload args=%v", args)
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

// readModelInvocations reads the argv records the fixture appended.
func readModelInvocations() ([][]string, error) {
	if modelInvocationLog == "" {
		return nil, fmt.Errorf("the model invocation log path was never assigned")
	}
	file, err := os.Open(modelInvocationLog)
	if err != nil {
		if os.IsNotExist(err) {
			return nil, nil
		}
		return nil, fmt.Errorf("open model invocation log: %w", err)
	}
	defer func() { _ = file.Close() }()
	var records [][]string
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
			return nil, fmt.Errorf("decode model invocation record %q: %w", line, err)
		}
		records = append(records, record.Argv)
	}
	if err := scanner.Err(); err != nil {
		return nil, fmt.Errorf("read model invocation log: %w", err)
	}
	return records, nil
}

// selectInvocations keeps only the argv records that carry a model select.
func selectInvocations(records [][]string) [][]string {
	selects := make([][]string, 0, len(records))
	for _, argv := range records {
		if containsArg(argv, "call_instruction") {
			selects = append(selects, argv)
		}
	}
	return selects
}

// containsArg reports whether one argv element equals the value exactly. An exact
// match is required: a substring match would accept "fixture-model-b" when looking
// for "2" only if the value appeared inside another argument, which is not what a
// leaked row number looks like.
func containsArg(argv []string, value string) bool {
	for _, arg := range argv {
		if arg == value {
			return true
		}
	}
	return false
}
