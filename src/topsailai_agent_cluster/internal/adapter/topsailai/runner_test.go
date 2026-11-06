package topsailai

import (
	"context"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

// helperEnvironmentVariable marks the provider role in
// TestExecRunnerSiblingHelper: when it is set the process spawns the sibling by
// bare name, and when it is absent the process is the sibling itself.
const helperEnvironmentVariable = "TOPSAILAI_TEST_PROVIDER_SIBLING"

// helperMarkerVariable activates the helper only in a spawned child, so a
// normal suite run never exits the test process.
const helperMarkerVariable = "TOPSAILAI_TEST_PROVIDER_HELPER"

func TestExecRunnerReturnsCommandOutputAndInput(t *testing.T) {
	runner := execRunner{timeout: 5 * time.Second}
	output, err := runner.Run(context.Background(), os.Args[0], []string{"-test.run=TestExecRunnerHelper", "--", "runner-input"}, []byte("input"))
	if err != nil {
		t.Fatal(err)
	}
	if string(output) != "runner-input:input" {
		t.Fatalf("output=%q", output)
	}
}

func TestExecRunnerReportsCommandFailure(t *testing.T) {
	runner := execRunner{timeout: time.Second}
	_, err := runner.Run(context.Background(), "definitely-not-a-real-provider-command", nil, nil)
	if err == nil || !strings.Contains(err.Error(), "run TopsailAI command") {
		t.Fatalf("error=%v", err)
	}
}

func TestExecRunnerReportsTimeout(t *testing.T) {
	runner := execRunner{timeout: time.Millisecond}
	_, err := runner.Run(context.Background(), os.Args[0], []string{"-test.run=TestExecRunnerHelper", "--", "runner-timeout"}, nil)
	if err == nil || !strings.Contains(err.Error(), "context deadline exceeded") {
		t.Fatalf("error=%v", err)
	}
}

func TestExecRunnerHelper(t *testing.T) {
	if len(os.Args) < 3 || os.Args[1] != "-test.run=TestExecRunnerHelper" {
		return
	}
	if len(os.Args) > 3 && os.Args[3] == "runner-timeout" {
		time.Sleep(time.Second)
		return
	}
	data := make([]byte, 32)
	n, _ := os.Stdin.Read(data)
	_, _ = os.Stdout.WriteString(os.Args[3] + ":" + string(data[:n]))
	os.Exit(0)
}

func TestProviderEnvironmentPrependsExecutableDirectory(t *testing.T) {
	environment := providerEnvironment("/opt/provider/bin/topsailai", []string{"HOME=/root", "PATH=/usr/bin:/bin"})
	if value := environmentValue(environment, "PATH"); value != "/opt/provider/bin"+string(os.PathListSeparator)+"/usr/bin:/bin" {
		t.Fatalf("PATH=%q", value)
	}
	if value := environmentValue(environment, "HOME"); value != "/root" {
		t.Fatalf("HOME=%q", value)
	}
}

func TestProviderEnvironmentDoesNotDuplicatePresentDirectory(t *testing.T) {
	inherited := "/opt/provider/bin:/usr/bin"
	environment := providerEnvironment("/opt/provider/bin/topsailai", []string{"PATH=" + inherited})
	if value := environmentValue(environment, "PATH"); value != inherited {
		t.Fatalf("PATH=%q", value)
	}
}

func TestProviderEnvironmentAddsPathWhenInheritedIsAbsent(t *testing.T) {
	environment := providerEnvironment("/opt/provider/bin/topsailai", []string{"HOME=/root"})
	if value := environmentValue(environment, "PATH"); value != "/opt/provider/bin" {
		t.Fatalf("PATH=%q", value)
	}
}

func TestProviderEnvironmentLeavesRelativeExecutableUnchanged(t *testing.T) {
	base := []string{"PATH=/usr/bin"}
	environment := providerEnvironment("topsailai", base)
	if len(environment) != len(base) || environment[0] != base[0] {
		t.Fatalf("environment=%v", environment)
	}
}

// TestExecRunnerResolvesSiblingProviderExecutable reproduces the endpoint
// failure: the provider CLI spawns a sibling executable by bare name, and the
// daemon PATH does not contain the provider directory.
//
// The test binary itself plays both roles, so the test needs no shell and no
// platform-specific script interpreter. The provider copy is named after the
// sibling it spawns, and the sibling copy reports that it was reached.
func TestExecRunnerResolvesSiblingProviderExecutable(t *testing.T) {
	directory := t.TempDir()
	sibling := "provider-sibling"
	provider := filepath.Join(directory, "provider-main")
	copyTestBinary(t, provider)
	copyTestBinary(t, filepath.Join(directory, sibling))
	t.Setenv("PATH", "/usr/bin:/bin")
	t.Setenv(helperEnvironmentVariable, sibling)
	t.Setenv(helperMarkerVariable, "1")
	runner := execRunner{timeout: 5 * time.Second}
	output, err := runner.Run(context.Background(), provider, []string{"-test.run=TestExecRunnerSiblingHelper", "--"}, nil)
	if err != nil {
		t.Fatalf("run provider: %v", err)
	}
	if strings.TrimSpace(string(output)) != "sibling-resolved" {
		t.Fatalf("output=%q", output)
	}
}

// TestExecRunnerSiblingHelper is the provider and sibling body used by
// TestExecRunnerResolvesSiblingProviderExecutable. It spawns the configured
// sibling by bare name, exactly as the real provider CLI spawns its launcher.
func TestExecRunnerSiblingHelper(t *testing.T) {
	if os.Getenv(helperMarkerVariable) == "" {
		return
	}
	sibling := os.Getenv(helperEnvironmentVariable)
	if sibling == "" {
		_, _ = os.Stdout.WriteString("sibling-resolved")
		os.Exit(0)
	}
	command := exec.Command(sibling, "-test.run=TestExecRunnerSiblingHelper", "--")
	command.Env = withoutEnvironment(os.Environ(), helperEnvironmentVariable)
	command.Stdout = os.Stdout
	if err := command.Run(); err != nil {
		_, _ = os.Stderr.WriteString(err.Error())
		os.Exit(1)
	}
	os.Exit(0)
}

func TestProviderEnvironmentLeavesRootInstalledExecutableUnchanged(t *testing.T) {
	base := []string{"PATH=/usr/bin"}
	environment := providerEnvironment("/topsailai", base)
	if len(environment) != len(base) || environment[0] != base[0] {
		t.Fatalf("environment=%v", environment)
	}
}

func environmentValue(environment []string, name string) string {
	for _, entry := range environment {
		if strings.HasPrefix(entry, name+"=") {
			return strings.TrimPrefix(entry, name+"=")
		}
	}
	return ""
}

// copyTestBinary copies the running test binary so it can act as a provider
// executable without depending on a shell interpreter.
func copyTestBinary(t *testing.T, destination string) {
	t.Helper()
	source, err := os.ReadFile(os.Args[0])
	if err != nil {
		t.Fatalf("read test binary: %v", err)
	}
	if err := os.WriteFile(destination, source, 0o755); err != nil {
		t.Fatalf("write %s: %v", destination, err)
	}
}

// withoutEnvironment returns base without the named variable, so a spawned
// child cannot inherit the role marker that selected its parent's role.
func withoutEnvironment(base []string, name string) []string {
	environment := make([]string, 0, len(base))
	for _, entry := range base {
		if strings.HasPrefix(entry, name+"=") {
			continue
		}
		environment = append(environment, entry)
	}
	return environment
}
