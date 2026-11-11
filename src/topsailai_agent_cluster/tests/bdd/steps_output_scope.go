package bdd

import (
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"

	"github.com/cucumber/godog"
	"topsailai_agent_cluster/internal/protocol"
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

// scopedEndpointID is the Endpoint identity the harness registers, so a scenario
// can name the same machine in the CLI token map and in the policy file.
const scopedEndpointID = "endpoint-1"

// scopedTokenName derives the token name from the granted scopes, so two
// scenarios that grant different scopes never share a token and a leaked token
// from one scenario cannot satisfy another.
func scopedTokenName(scopes []string) string {
	return "bdd-" + strings.Join(scopes, "-") + "-token"
}

// scopedEndpointTokenMap renders the CLI token map for the fixture Endpoint.
func scopedEndpointTokenMap(token string) string {
	return scopedEndpointID + "=" + token
}

// writeAccessPolicyDir writes one policy file per token into the scenario's
// temporary directory and returns the directory path.
//
// The policy is a directory of files rather than one environment value because
// that is the only shape the Endpoint reads: one file per caller token. Writing
// the files is what makes the Endpoint restricted, so a scenario that forgot to
// write them would run against a permissive Endpoint and prove nothing while
// appearing to prove the configured restriction.
func writeAccessPolicyDir(tokens map[string][]string) (string, error) {
	if activeTest == nil {
		return "", fmt.Errorf("active BDD test is not initialized")
	}
	dir := filepath.Join(activeTest.TempDir(), "endpoint-access.d")
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return "", fmt.Errorf("create access policy directory: %w", err)
	}
	names := make([]string, 0, len(tokens))
	for name := range tokens {
		names = append(names, name)
	}
	// Sorted so a failing scenario reproduces the same directory every run.
	sort.Strings(names)
	for _, name := range names {
		lines := []string{"token " + name}
		if scopes := tokens[name]; len(scopes) > 0 {
			lines = append(lines, "scopes "+strings.Join(scopes, " "))
		}
		path := filepath.Join(dir, name+".conf")
		if err := os.WriteFile(path, []byte(strings.Join(lines, "\n")+"\n"), 0o600); err != nil {
			return "", fmt.Errorf("write access policy file %q: %w", path, err)
		}
	}
	return dir, nil
}

// startViewOnlyCluster starts a real cluster whose Endpoint grants one token the
// view scope only. Narrowing the grant is the whole point: an Endpoint with no
// policy directory permits every caller, so a cluster started without the policy
// would let the request through and the scenario would pass while proving
// nothing.
func startViewOnlyCluster() error {
	return startScopedCluster([]string{security.ScopeView})
}

// startReadOutputCluster starts a real cluster whose credential holds the
// read_output scope, so the scenario can prove the check admits a permitted
// caller instead of refusing everyone.
func startReadOutputCluster() error {
	return startScopedCluster([]string{security.ScopeReadOutput})
}

// startScopedCluster starts a real cluster whose Endpoint holds one access
// policy file granting exactly the given scopes to one token, and whose CLI
// presents that token for the fixture Endpoint.
//
// The restriction is written on the Endpoint, not on the Server, because the
// Endpoint is the only component that decides whether a caller may exercise an
// operation. A scenario that narrowed the Server instead would prove nothing:
// the Server forwards every request and holds no authority to refuse one.
func startScopedCluster(scopes []string) error {
	if activeTest == nil {
		return fmt.Errorf("active BDD test is not initialized")
	}
	if activeScenario.world == nil {
		activeScenario.world = &World{}
	}
	token := scopedTokenName(scopes)
	policyDir, err := writeAccessPolicyDir(map[string][]string{token: scopes})
	if err != nil {
		return err
	}
	cluster, err := harness.StartCluster(activeTest, harness.ClusterOptions{
		EndpointEnvironment: map[string]string{"AGENT_CLUSTER_ENDPOINT_ACCESS_POLICY_DIR": policyDir},
		CLIEnvironment:      map[string]string{"AGENT_CLUSTER_ENDPOINT_TOKENS": scopedEndpointTokenMap(token)},
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
// The assertion is the Endpoint's own refusal code, not an HTTP status. A
// snapshot refusal arrives as 403, but a follow refusal arrives as a terminal
// record inside a 200 stream, because the stream had already started before the
// Endpoint could answer. Asserting the code is therefore the only statement that
// holds for both surfaces, and it is also the statement that matters: the code is
// what tells the operator the Endpoint refused rather than failed.
//
// The assertion also rejects any provider output in the response, so a refusal
// that leaked data before failing cannot pass.
func assertRefusedForScope(surface string) error {
	text := string(activeScenario.lastBody)
	if !strings.Contains(text, protocol.PolicyDenied) {
		return fmt.Errorf("the %s refusal does not report the %q code: exit=%d output=%s", surface, protocol.PolicyDenied, activeScenario.lastStatus, text)
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
