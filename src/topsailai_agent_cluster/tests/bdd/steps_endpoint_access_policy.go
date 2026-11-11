package bdd

import (
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"syscall"
	"time"

	"github.com/cucumber/godog"
	"topsailai_agent_cluster/internal/protocol"
	"topsailai_agent_cluster/tests/harness"
)

const (
	policyProbeToken = "bdd-policy-probe-token"
	policyProbeFile  = "probe.conf"
)

var (
	policyProbeDir     string
	policyProbeLogPath string
	policyProbeBefore  int
)

// registerEndpointAccessPolicySteps registers executable policy-management scenarios.
func registerEndpointAccessPolicySteps(ctx *godog.ScenarioContext) {
	ctx.Step(`^a real cluster with no Endpoint access policy directory$`, startPolicyProbeWithoutDirectory)
	ctx.Step(`^a real cluster with an empty Endpoint access policy directory$`, startPolicyProbeWithEmptyDirectory)
	ctx.Step(`^a real cluster whose Endpoint policy grants output read to its registered token$`, startPolicyProbeWithOutputGrant)
	ctx.Step(`^the CLI uses the (missing|wrong|unlisted) Endpoint credential$`, usePolicyProbeCredential)
	ctx.Step(`^a real cluster whose token is restricted to another Endpoint$`, startPolicyProbeForAnotherEndpoint)
	ctx.Step(`^a real cluster whose token has view scope and output read permission$`, startPolicyProbeWithUnionGrant)
	ctx.Step(`^a real cluster whose token is allowed every operation$`, startPolicyProbeWithAllowAll)
	ctx.Step(`^a real cluster whose token is denied every operation$`, startPolicyProbeWithDenyAll)
	ctx.Step(`^a real cluster whose Endpoint policy stores a hash of the CLI token$`, startPolicyProbeWithHashedToken)
	ctx.Step(`^a real cluster whose policy initially denies output read$`, startPolicyProbeWithDenyAll)
	ctx.Step(`^a real cluster whose policy initially grants output read$`, startPolicyProbeWithOutputGrant)
	ctx.Step(`^the policy is replaced with an output read grant and reloaded$`, reloadPolicyProbeWithOutputGrant)
	ctx.Step(`^the policy is replaced with a malformed rule and reload is attempted$`, reloadPolicyProbeWithMalformedRule)
	ctx.Step(`^the policy probe reads session output$`, runPolicyProbe)
	ctx.Step(`^the policy probe reaches the provider$`, assertPolicyProbeReachedProvider)
	ctx.Step(`^the policy probe is refused before provider invocation$`, assertPolicyProbeRefusedBeforeProvider)
}

func startPolicyProbeWithoutDirectory() error {
	return startPolicyProbeCluster("", policyProbeToken)
}

func startPolicyProbeWithEmptyDirectory() error {
	dir, err := newPolicyProbeDirectory()
	if err != nil {
		return err
	}
	return startPolicyProbeCluster(dir, policyProbeToken)
}

func startPolicyProbeWithOutputGrant() error {
	return startPolicyProbeWithRule("token " + policyProbeToken + "\npermissions output.read\n")
}

func startPolicyProbeForAnotherEndpoint() error {
	return startPolicyProbeWithRule("token " + policyProbeToken + "\nendpoints another-endpoint\npermissions output.read\n")
}

func startPolicyProbeWithUnionGrant() error {
	return startPolicyProbeWithRule("token " + policyProbeToken + "\nscopes view\npermissions output.read\n")
}

func startPolicyProbeWithAllowAll() error {
	return startPolicyProbeWithRule("token " + policyProbeToken + "\nallow-all\n")
}

func startPolicyProbeWithDenyAll() error {
	return startPolicyProbeWithRule("token " + policyProbeToken + "\ndeny-all\n")
}

func startPolicyProbeWithHashedToken() error {
	sum := sha256.Sum256([]byte(policyProbeToken))
	return startPolicyProbeWithRule("token-sha256 " + hex.EncodeToString(sum[:]) + "\npermissions output.read\n")
}

func startPolicyProbeWithRule(rule string) error {
	dir, err := newPolicyProbeDirectory()
	if err != nil {
		return err
	}
	if err := writePolicyProbeRule(dir, rule); err != nil {
		return err
	}
	return startPolicyProbeCluster(dir, policyProbeToken)
}

func newPolicyProbeDirectory() (string, error) {
	if activeTest == nil {
		return "", fmt.Errorf("active BDD test is not initialized")
	}
	dir := filepath.Join(activeTest.TempDir(), "endpoint-access-policy")
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return "", fmt.Errorf("create policy probe directory: %w", err)
	}
	policyProbeDir = dir
	return dir, nil
}

func writePolicyProbeRule(dir, rule string) error {
	path := filepath.Join(dir, policyProbeFile)
	if err := os.WriteFile(path, []byte(rule), 0o600); err != nil {
		return fmt.Errorf("write policy probe rule: %w", err)
	}
	return nil
}

func startPolicyProbeCluster(policyDir, token string) error {
	if activeTest == nil {
		return fmt.Errorf("active BDD test is not initialized")
	}
	if activeScenario.world == nil {
		activeScenario.world = &World{}
	}
	policyProbeDir = policyDir
	policyProbeLogPath = filepath.Join(activeTest.TempDir(), "endpoint.log")
	endpointEnv := map[string]string{
		"AGENT_CLUSTER_LOG_OUTPUT": "file",
		"AGENT_CLUSTER_LOG_PATH":   policyProbeLogPath,
	}
	if policyDir != "" {
		endpointEnv["AGENT_CLUSTER_ENDPOINT_ACCESS_POLICY_DIR"] = policyDir
	}
	cliEnv := map[string]string{}
	if token != "" {
		cliEnv["AGENT_CLUSTER_ENDPOINT_TOKENS"] = scopedEndpointTokenMap(token)
	}
	cluster, err := harness.StartCluster(activeTest, harness.ClusterOptions{
		EndpointEnvironment: endpointEnv,
		CLIEnvironment:      cliEnv,
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

func usePolicyProbeCredential(kind string) error {
	if activeScenario.realCluster == nil {
		return fmt.Errorf("real cluster is not running")
	}
	switch kind {
	case "missing":
		activeScenario.realCluster.CLIEnv = nil
	case "wrong":
		activeScenario.realCluster.CLIEnv = []string{"AGENT_CLUSTER_ENDPOINT_TOKENS=" + scopedEndpointTokenMap("wrong-token")}
	case "unlisted":
		activeScenario.realCluster.CLIEnv = []string{"AGENT_CLUSTER_ENDPOINT_TOKENS=" + scopedEndpointTokenMap("unlisted-token")}
	default:
		return fmt.Errorf("unknown credential kind %q", kind)
	}
	return nil
}

func runPolicyProbe() error {
	if activeScenario.realCluster == nil {
		return fmt.Errorf("real cluster is not running")
	}
	before, err := activeScenario.realCluster.ProviderInvocationsE()
	if err != nil {
		return err
	}
	policyProbeBefore = countPolicyProbeInvocations(before)
	resourceID, err := tuiResourceID()
	if err != nil {
		return err
	}
	stdout, stderr, code, runErr := activeScenario.realCluster.RunTUI("logs", scopedEndpointID, resourceID)
	activeScenario.lastBody = []byte(stdout + stderr)
	activeScenario.lastStatus = code
	if runErr != nil && code == 0 {
		return fmt.Errorf("run policy probe: %v stderr=%s", runErr, stderr)
	}
	return nil
}

func countPolicyProbeInvocations(records []map[string]any) int {
	count := 0
	for _, record := range records {
		if record["operation"] == protocol.OperationOutputRead {
			count++
		}
	}
	return count
}

func policyProbeInvocationCount() (int, error) {
	records, err := activeScenario.realCluster.ProviderInvocationsE()
	if err != nil {
		return 0, err
	}
	return countPolicyProbeInvocations(records), nil
}

func assertPolicyProbeReachedProvider() error {
	text := string(activeScenario.lastBody)
	if activeScenario.lastStatus != 0 {
		return fmt.Errorf("policy probe failed: exit=%d output=%s", activeScenario.lastStatus, text)
	}
	if !strings.Contains(text, "provider output marker") {
		return fmt.Errorf("policy probe returned no provider output: %s", text)
	}
	count, err := policyProbeInvocationCount()
	if err != nil {
		return err
	}
	if count != policyProbeBefore+1 {
		return fmt.Errorf("provider output invocation count=%d, want %d", count, policyProbeBefore+1)
	}
	return nil
}

func assertPolicyProbeRefusedBeforeProvider() error {
	text := string(activeScenario.lastBody)
	if !strings.Contains(text, protocol.PolicyDenied) {
		return fmt.Errorf("policy refusal does not report %q: exit=%d output=%s", protocol.PolicyDenied, activeScenario.lastStatus, text)
	}
	count, err := policyProbeInvocationCount()
	if err != nil {
		return err
	}
	if count != policyProbeBefore {
		return fmt.Errorf("refused policy probe reached provider: before=%d after=%d", policyProbeBefore, count)
	}
	return nil
}

func reloadPolicyProbeWithOutputGrant() error {
	if err := writePolicyProbeRule(policyProbeDir, "token "+policyProbeToken+"\npermissions output.read\n"); err != nil {
		return err
	}
	return signalPolicyReloadAndWait("reloaded endpoint access policy")
}

func reloadPolicyProbeWithMalformedRule() error {
	if err := writePolicyProbeRule(policyProbeDir, "token "+policyProbeToken+"\nunknown-directive value\n"); err != nil {
		return err
	}
	return signalPolicyReloadAndWait("reload endpoint access policy")
}

func signalPolicyReloadAndWait(marker string) error {
	cluster := activeScenario.realCluster
	if cluster == nil || cluster.Endpoint == nil || cluster.Endpoint.Process == nil {
		return fmt.Errorf("Endpoint process is not running")
	}
	before, err := os.ReadFile(policyProbeLogPath)
	if err != nil && !os.IsNotExist(err) {
		return fmt.Errorf("read Endpoint log before reload: %w", err)
	}
	if err := cluster.Endpoint.Process.Signal(syscall.SIGHUP); err != nil {
		return fmt.Errorf("signal owned Endpoint pid %d: %w", cluster.Endpoint.Process.Pid, err)
	}
	deadline := time.Now().Add(5 * time.Second)
	for time.Now().Before(deadline) {
		data, readErr := os.ReadFile(policyProbeLogPath)
		if readErr != nil && !os.IsNotExist(readErr) {
			return fmt.Errorf("read Endpoint reload log: %w", readErr)
		}
		if len(data) > len(before) && strings.Contains(string(data[len(before):]), marker) {
			return nil
		}
		time.Sleep(20 * time.Millisecond)
	}
	return fmt.Errorf("Endpoint did not log %q after SIGHUP", marker)
}
