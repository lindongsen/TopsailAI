package bdd

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"github.com/cucumber/godog"
	"topsailai_agent_cluster/tests/harness"
)

// The CLI failover scenarios drive the real CLI binary against two real Servers.
//
// Nothing here is simulated. The probe is a real HTTP request to a real readiness
// route, the fallback happens because a real process is gone, and the sticky
// preference is a real file in the CLI's own home directory. A stub would prove
// that the selector was called, never that the CLI reaches the Server it reports.
//
// The state below is package-level rather than a field on Scenario because these
// scenarios run one at a time and every value is reset by the Given step. Adding
// fields to the shared Scenario struct would make every other step file carry
// state that only this feature uses.
var (
	cliFailoverStderr     string
	cliFailoverStdout     string
	cliFailoverExit       int
	cliFailoverStickyPath string
	cliFailoverGroup      string
)

// cliFailoverStickyEnv names the file that remembers the last Server that
// answered.
//
// It is set explicitly instead of relying on the default location, so the
// scenario can read and seed the exact file the CLI uses. Relying on the default
// would make the assertion depend on the CLI's home-directory resolution, which
// is a different behaviour from the one under test.
const cliFailoverStickyEnv = "AGENT_CLUSTER_CLI_SERVER_PROFILE_STICKY_FILE"

// startCLIFailoverCluster starts a real cluster with a second independent Server
// and configures the CLI's profile maps.
//
// The second Server must own its own database, because a shared database would
// make the fallback scenario pass for the wrong reason: the "second" Server would
// already hold the primary's state, so a request that reached it could not be
// distinguished from a request that reached the primary.
//
// The profile maps are CLI configuration, so they belong in CLIEnvironment. The
// Server never holds them: a Server that knew the fleet's profiles would be a
// second place that decides which Server a caller may use.
func startCLIFailoverCluster() error {
	if activeTest == nil {
		return fmt.Errorf("active BDD test is not initialized")
	}
	// Only the scenario name is sanitized. Sanitizing the whole path would strip
	// the leading separator of the temporary directory and leave a relative path,
	// which the CLI would then resolve against its own working directory instead
	// of the one this step seeded.
	descriptor := strings.NewReplacer(" ", "-", "/", "-", ":", "-").Replace(activeScenario.scenarioName)
	root := filepath.Join(os.TempDir(), "bdd-cli-failover-"+descriptor)
	cliFailoverStickyPath = filepath.Join(root, "sticky-profile")
	// The path is derived from the scenario name, so it survives between runs. A
	// remembered profile left by an earlier run would reorder the candidates and
	// make a scenario observe a walk that never happened: the remembered Server
	// answers first, so the unreachable one is never probed and never reported as
	// skipped. Removing it here makes every scenario start from "nothing is
	// remembered", which is the state the Given step claims.
	if err := os.Remove(cliFailoverStickyPath); err != nil && !os.IsNotExist(err) {
		return fmt.Errorf("clear remembered profile: %w", err)
	}
	cliFailoverStderr = ""
	cliFailoverStdout = ""
	cliFailoverExit = 0
	cliFailoverGroup = ""
	cluster, err := harness.StartCluster(activeTest, harness.ClusterOptions{
		SecondServer: true,
		CLIEnvironment: map[string]string{
			cliFailoverStickyEnv: cliFailoverStickyPath,
		},
	})
	if err != nil {
		return err
	}
	// The profile maps are written after the cluster exists, because each entry
	// names a port the harness allocated. They are appended to the cluster's own
	// CLI environment so the CLI sees one consistent configuration.
	cluster.CLIEnv = append(cluster.CLIEnv,
		"AGENT_CLUSTER_CLI_SERVER_PROFILES=primary="+cluster.URL("")+",secondary="+cluster.SecondaryURL(""),
		"AGENT_CLUSTER_CLI_SERVER_PROFILE_TOKENS=primary=secret,secondary=secret",
	)
	activeScenario.world = &World{realCluster: cluster}
	return nil
}

// runCLIWithProfileGroup runs one read command with an explicit profile group.
//
// The group is passed as a flag rather than through the environment so each
// scenario states its own group. The environment carries the profile maps, which
// are deployment configuration, while the group is the per-invocation choice.
//
// `list` is the command because it is a read: a write would make a fallback
// scenario ambiguous, since a request that reached the wrong Server could have
// changed state there.
func runCLIWithProfileGroup(group string) error {
	cluster := activeScenario.world.realCluster
	if cluster == nil {
		return fmt.Errorf("no real cluster is running")
	}
	if _, err := cluster.BuildTUI(activeTest); err != nil {
		return err
	}
	cliFailoverGroup = group
	stdout, stderr, code, runErr := cluster.RunTUI("--server-profile", group, "list")
	cliFailoverStdout = stdout
	cliFailoverStderr = stderr
	cliFailoverExit = code
	// A non-zero exit is a scenario outcome, not a harness failure, so the error
	// is recorded rather than returned. The scenarios that expect a failure assert
	// on it; the ones that expect success assert on the exit code.
	_ = runErr
	return nil
}

// cliRememberedProfile seeds the sticky file with a profile name.
//
// It writes the file directly instead of running the CLI twice, because the
// behaviour under test is "a remembered Server is tried first", not "a successful
// invocation writes the file". Running the CLI first would make the scenario
// depend on the write path it is not testing, and a defect in that path would
// fail the wrong scenario.
func cliRememberedProfile(name string) error {
	if cliFailoverStickyPath == "" {
		return fmt.Errorf("the sticky profile path is not configured")
	}
	if err := os.MkdirAll(filepath.Dir(cliFailoverStickyPath), 0o700); err != nil {
		return fmt.Errorf("create sticky directory: %w", err)
	}
	if err := os.WriteFile(cliFailoverStickyPath, []byte(name+"\n"), 0o600); err != nil {
		return fmt.Errorf("seed sticky profile: %w", err)
	}
	return nil
}

// stopPrimaryServer removes the first Server so the walk must continue.
func stopPrimaryServer() error {
	cluster := activeScenario.world.realCluster
	if cluster == nil {
		return fmt.Errorf("no real cluster is running")
	}
	return cluster.StopPrimaryServerE()
}

// stopSecondaryServer removes the second Server so no candidate is reachable.
func stopSecondaryServer() error {
	cluster := activeScenario.world.realCluster
	if cluster == nil {
		return fmt.Errorf("no real cluster is running")
	}
	return harness.StopProcessE(cluster.SecondaryServer)
}

// cliExitedSuccessfully asserts the invocation succeeded.
func cliExitedSuccessfully() error {
	if cliFailoverExit != 0 {
		return fmt.Errorf("CLI exited %d, want 0; stderr=%s", cliFailoverExit, cliFailoverStderr)
	}
	return nil
}

// cliFailed asserts the invocation failed.
func cliFailed() error {
	if cliFailoverExit == 0 {
		return fmt.Errorf("CLI exited 0, want a failure; stdout=%s stderr=%s", cliFailoverStdout, cliFailoverStderr)
	}
	return nil
}

// cliReportedProfile asserts the CLI named the Server it used.
//
// The assertion is on diagnostics rather than output, because a --json document
// must stay machine-readable. It matches the whole reported phrase so a profile
// name that merely appears somewhere else in the diagnostics cannot satisfy it.
func cliReportedProfile(name string) error {
	want := fmt.Sprintf("using server profile %q", name)
	if !strings.Contains(cliFailoverStderr, want) {
		return fmt.Errorf("CLI diagnostics do not contain %q; stderr=%s", want, cliFailoverStderr)
	}
	return nil
}

// cliReportedNoSelection asserts the CLI reported no selection at all.
//
// A group of one is used without probing, so it must also be silent. A diagnostic
// line here would mean the single-Server path had gained a probe, which is the
// behaviour change this feature exists to avoid.
func cliReportedNoSelection() error {
	if strings.Contains(cliFailoverStderr, "using server profile") {
		return fmt.Errorf("CLI reported a server selection for a single profile; stderr=%s", cliFailoverStderr)
	}
	return nil
}

// cliReportedNoSkippedServer asserts no candidate was skipped.
func cliReportedNoSkippedServer() error {
	if strings.Contains(cliFailoverStderr, "skipped") {
		return fmt.Errorf("CLI reported a skipped server, want none; stderr=%s", cliFailoverStderr)
	}
	return nil
}

// cliReportedSkippedProfile asserts one named candidate was skipped.
func cliReportedSkippedProfile(name string) error {
	want := fmt.Sprintf("server %q skipped", name)
	if !strings.Contains(cliFailoverStderr, want) {
		return fmt.Errorf("CLI diagnostics do not contain %q; stderr=%s", want, cliFailoverStderr)
	}
	return nil
}

// cliErrorNamesProfile asserts the failure names one candidate it tried.
//
// The names are the only evidence that separates "no Server is reachable" from
// "this Server refused me", so a failure that omits them leaves the operator
// unable to tell a single-Server outage from a fleet-wide one.
func cliErrorNamesProfile(name string) error {
	if !strings.Contains(cliFailoverStderr, name) {
		return fmt.Errorf("CLI error does not name profile %q; stderr=%s", name, cliFailoverStderr)
	}
	return nil
}

// cliWroteNoStickyProfile asserts the preference file was not created.
func cliWroteNoStickyProfile() error {
	if cliFailoverStickyPath == "" {
		return fmt.Errorf("the sticky profile path is not configured")
	}
	if _, err := os.Stat(cliFailoverStickyPath); err == nil {
		content, _ := os.ReadFile(cliFailoverStickyPath)
		return fmt.Errorf("CLI wrote a remembered profile %q for a single-profile invocation", strings.TrimSpace(string(content)))
	} else if !os.IsNotExist(err) {
		return fmt.Errorf("stat sticky profile: %w", err)
	}
	return nil
}

// registerCLIFailoverSteps registers the CLI Server failover steps.
func registerCLIFailoverSteps(ctx *godog.ScenarioContext) {
	ctx.Step(`^a real cluster with a second independent server$`, startCLIFailoverCluster)
	ctx.Step(`^the CLI remembers server profile "([^"]*)"$`, cliRememberedProfile)
	ctx.Step(`^the primary server is stopped$`, stopPrimaryServer)
	ctx.Step(`^the second server is stopped$`, stopSecondaryServer)
	ctx.Step(`^the CLI runs a read command with the profile group "([^"]*)"$`, runCLIWithProfileGroup)
	ctx.Step(`^the CLI exits successfully$`, cliExitedSuccessfully)
	ctx.Step(`^the CLI fails$`, cliFailed)
	ctx.Step(`^the CLI reports it used server profile "([^"]*)"$`, cliReportedProfile)
	ctx.Step(`^the CLI reports no server selection$`, cliReportedNoSelection)
	ctx.Step(`^the CLI reports no skipped server$`, cliReportedNoSkippedServer)
	ctx.Step(`^the CLI reports server profile "([^"]*)" as skipped$`, cliReportedSkippedProfile)
	ctx.Step(`^the CLI error names server profile "([^"]*)"$`, cliErrorNamesProfile)
	ctx.Step(`^the CLI writes no remembered server profile$`, cliWroteNoStickyProfile)
}
