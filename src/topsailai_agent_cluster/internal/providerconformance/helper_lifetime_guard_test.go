package providerconformance

import (
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
)

// helperGuardExecutableTestFile is the conformance suite that carries the
// helper-leak cases.
const helperGuardExecutableTestFile = "executable_test.go"

// helperGuardSource reads one file from this package directory.
func helperGuardSource(t *testing.T, name string) string {
	t.Helper()
	return repoText(t, "internal", "providerconformance", name)
}

// helperGuardFunc returns the body of one function, tolerating a return type
// between the parameter list and the opening brace.
func helperGuardFunc(t *testing.T, source, name string) string {
	t.Helper()
	marker := "func " + name + "("
	start := strings.Index(source, marker)
	if start < 0 {
		t.Fatalf("the source does not declare %s", name)
	}
	rest := source[start:]
	brace := strings.Index(rest, "{")
	if brace < 0 {
		t.Fatalf("%s has no body", name)
	}
	rest = rest[brace:]
	end := strings.Index(rest, "\n}\n")
	if end < 0 {
		t.Fatalf("%s has no closing brace", name)
	}
	return rest[:end]
}

// TestHelperLeakCaseAssertsTheProcessIsGone pins the completion case. The row
// says a helper must not survive completion, so the case has to start a helper,
// require the leak error, and then observe the process itself. An error string
// alone would prove only that the runner noticed something.
func TestHelperLeakCaseAssertsTheProcessIsGone(t *testing.T) {
	source := helperGuardSource(t, helperGuardExecutableTestFile)
	body := functionBody(t, source, "TestMockProviderHelperLeakIsDetected")
	if !strings.Contains(body, `"helper-leak"`) {
		t.Fatal("the completion case does not select the helper-leak fault, so no helper is ever started")
	}
	if !strings.Contains(body, `"helper leaked"`) {
		t.Fatal("the completion case does not require the leaked-helper error, so a silent leak would pass")
	}
	if !strings.Contains(body, "assertReportedHelperGone") {
		t.Fatal("the completion case does not check the helper process, so only the error text is proven")
	}
}

// TestTimeoutAndCancellationAssertTheHelperIsGone pins the other two halves of
// the row. Completion, timeout and cancellation are three separate exits, and a
// helper that survives only one of them still violates the row.
func TestTimeoutAndCancellationAssertTheHelperIsGone(t *testing.T) {
	source := helperGuardSource(t, helperGuardExecutableTestFile)
	body := functionBody(t, source, "TestMockProviderTimeoutAndCancellation")
	for _, required := range []string{
		`t.Run("deadline"`,
		`t.Run("cancellation"`,
		`"invocation deadline"`,
		`"context canceled"`,
	} {
		if !strings.Contains(body, required) {
			t.Fatalf("the timeout case does not carry %q", required)
		}
	}
	if count := strings.Count(body, "assertReportedHelperGone"); count != 2 {
		t.Fatalf("the timeout case checks the helper %d times, want 2 (deadline and cancellation)", count)
	}
}

// TestHelperGoneCheckUsesARealProcessProbe pins the observation itself. The
// check must read the helper PID the mock reported and then ask the operating
// system whether that process still exists. A check that only inspects the
// error text would pass on a helper that is still running.
func TestHelperGoneCheckUsesARealProcessProbe(t *testing.T) {
	source := helperGuardSource(t, helperGuardExecutableTestFile)
	body := helperGuardFunc(t, source, "assertReportedHelperGone")
	if !strings.Contains(body, "helper_pid=") {
		t.Fatal("the helper check does not read the helper PID, so it cannot observe the process it claims is gone")
	}
	if !strings.Contains(body, "processAlive") {
		t.Fatal("the helper check does not probe the process, so it only proves the error text")
	}
	if !strings.Contains(body, "still alive") {
		t.Fatal("the helper check does not fail when the process survives")
	}

	unix := helperGuardSource(t, "process_unix.go")
	probe := helperGuardFunc(t, unix, "processAlive")
	if !strings.Contains(probe, "syscall.Kill") {
		t.Fatal("processAlive does not issue a real signal, so the check is not an operating-system probe")
	}
}

// TestRunnerKillsTheProcessGroupBeforeReportingALeak pins the mechanism the
// observation depends on. The runner must kill the invocation's process group
// and confirm the exit before it reports a leak, and the group must be created
// so a kill can reach a helper the provider started.
func TestRunnerKillsTheProcessGroupBeforeReportingALeak(t *testing.T) {
	runner := helperGuardSource(t, "runner.go")
	start := strings.Index(runner, "if processGroupAlive(command) {")
	if start < 0 {
		t.Fatal("runner.go does not check whether the process group survived the invocation")
	}
	block := runner[start:]
	end := strings.Index(block, "\n\t}\n")
	if end < 0 {
		t.Fatal("runner.go has no closing brace for the process-group check")
	}
	block = block[:end]
	kill := strings.Index(block, "killProcessGroup")
	wait := strings.Index(block, "waitForProcessGroupExit")
	leak := strings.Index(block, "helper leaked after completion")
	if kill < 0 || wait < 0 || leak < 0 {
		t.Fatalf("the process-group check is incomplete: kill=%d wait=%d leak=%d", kill, wait, leak)
	}
	if !(kill < wait && wait < leak) {
		t.Fatalf("the process-group check reports a leak before it kills and confirms the exit: kill=%d wait=%d leak=%d", kill, wait, leak)
	}

	unix := helperGuardSource(t, "process_unix.go")
	configure := helperGuardFunc(t, unix, "configureProcessGroup")
	if !strings.Contains(configure, "Setpgid") {
		t.Fatal("configureProcessGroup does not put the helper in the invocation's own group, so a kill cannot reach it")
	}
}

// TestHelperLeakCasesReallyRunUnderTheConformanceTarget builds the Mock
// Provider and runs the cases through a nested test binary. This is the only
// assertion that proves the cases execute rather than skip.
func TestHelperLeakCasesReallyRunUnderTheConformanceTarget(t *testing.T) {
	if testing.Short() {
		t.Skip("builds the Mock Provider and runs a nested test binary")
	}

	moduleDir := filepath.Join("..", "..", "providers", "mock")
	binary := filepath.Join(t.TempDir(), "agent-cluster-provider-mock")

	build := exec.Command("go", "build", "-o", binary, ".")
	build.Dir = moduleDir
	if output, err := build.CombinedOutput(); err != nil {
		t.Fatalf("build the Mock Provider: %v\n%s", err, output)
	}

	run := exec.Command("go", "test", "-count=1", "-v",
		"-run", "^TestMockProviderHelperLeakIsDetected$|^TestMockProviderTimeoutAndCancellation$",
		"./internal/providerconformance")
	run.Dir = filepath.Join("..", "..")
	run.Env = append(withoutVariable(os.Environ(), providerExecutableEnvironment),
		mockExecutableEnvironment+"="+binary)
	output, err := run.CombinedOutput()
	if err != nil {
		t.Fatalf("run the helper-leak cases: %v\n%s", err, output)
	}

	text := string(output)
	if strings.Contains(text, "--- SKIP") {
		t.Fatalf("a helper-leak case skipped even with the Mock Provider set:\n%s", text)
	}
	for _, name := range []string{"TestMockProviderHelperLeakIsDetected", "TestMockProviderTimeoutAndCancellation"} {
		if !strings.Contains(text, "--- PASS: "+name) {
			t.Fatalf("%s did not pass:\n%s", name, text)
		}
	}
}
