package providerconformance

import (
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
)

// executableTestFile is the conformance suite that carries the success and
// unsupported cases this guard pins.
const executableTestFile = "executable_test.go"

// readExecutableTest returns the source of the conformance suite.
func readExecutableTest(t *testing.T) string {
	t.Helper()
	data, err := os.ReadFile(executableTestFile)
	if err != nil {
		t.Fatalf("read %s: %v", executableTestFile, err)
	}
	return string(data)
}

// functionBody returns the source of one top-level test function, from its
// declaration to the closing brace at column zero. Extracting the body keeps a
// token that appears in a neighbouring test from satisfying an assertion.
func functionBody(t *testing.T, source, name string) string {
	t.Helper()
	marker := "func " + name + "(t *testing.T)"
	start := strings.Index(source, marker)
	if start < 0 {
		t.Fatalf("%s does not declare %s", executableTestFile, name)
	}
	rest := source[start:]
	// The declaration may carry a return type, so the body starts at the first
	// opening brace after the parameter list rather than at the marker itself.
	brace := strings.Index(rest, "{")
	if brace < 0 {
		t.Fatalf("%s has no body for %s", executableTestFile, name)
	}
	rest = rest[brace:]
	end := strings.Index(rest, "\n}\n")
	if end < 0 {
		t.Fatalf("%s has no closing brace for %s", executableTestFile, name)
	}
	return rest[:end]
}

// TestDefaultConformanceExercisesBothDirections pins that the default
// conformance test really asserts a successful exchange and really restricts
// itself to the functions the Provider advertised.
func TestDefaultConformanceExercisesBothDirections(t *testing.T) {
	body := functionBody(t, readExecutableTest(t), "TestProviderDefaultConformance")

	successAnchors := []string{
		`descriptorResponse.Descriptor == nil`,
		`providercli.NegotiateVersion(descriptorResponse.Descriptor.ProtocolRange)`,
		`requestFor(providercli.FunctionDiscover)`,
		`firstObservation.ProviderResourceKey != secondObservation.ProviderResourceKey`,
		`firstObservation.ResourceKind != secondObservation.ResourceKind`,
		`firstObservation.ProviderGeneration != secondObservation.ProviderGeneration`,
	}
	for _, anchor := range successAnchors {
		if !strings.Contains(body, anchor) {
			t.Fatalf("TestProviderDefaultConformance no longer asserts the success direction: %q is missing", anchor)
		}
	}

	if strings.Count(body, `requestFor(providercli.FunctionDiscover)`) != 2 {
		t.Fatalf("TestProviderDefaultConformance invokes discover %d times, so provider identity stability is not proven across two calls",
			strings.Count(body, `requestFor(providercli.FunctionDiscover)`))
	}

	unsupportedAnchors := []string{
		`case providercli.FunctionDescribe, providercli.FunctionDiscover, providercli.FunctionWatch:`,
		`case providercli.FunctionFollowOutput:`,
		`continue`,
	}
	for _, anchor := range unsupportedAnchors {
		if !strings.Contains(body, anchor) {
			t.Fatalf("TestProviderDefaultConformance no longer restricts itself to advertised functions: %q is missing", anchor)
		}
	}

	if strings.Contains(body, `for _, function := range descriptorResponse.Descriptor.Functions {`) == false {
		t.Fatal("TestProviderDefaultConformance no longer iterates the advertised function list")
	}
}

// TestUnsupportedFunctionRequiresTheUnsupportedCode pins that the unsupported
// case asserts the specific error code rather than any failure at all.
func TestUnsupportedFunctionRequiresTheUnsupportedCode(t *testing.T) {
	body := functionBody(t, readExecutableTest(t), "TestProviderUnsupportedFunction")

	if !strings.Contains(body, `response.Error.Code != "unsupported"`) {
		t.Fatal("TestProviderUnsupportedFunction does not require the unsupported error code, so any failure would satisfy it")
	}
	if !strings.Contains(body, `requestFor(providercli.FunctionWatch)`) {
		t.Fatal("TestProviderUnsupportedFunction no longer exercises the watch function")
	}
	if strings.Contains(body, "requireMock(") {
		t.Fatal("TestProviderUnsupportedFunction calls requireMock, so it skips whenever another Provider is selected")
	}
}

// TestConformanceTestsAreNotSilentlySkipped pins the only skip path the two
// cases may take. A plain package run reports PASS while both cases skip, so the
// skip must be reachable only through mockExecutable and must name the target
// that sets the variable.
func TestConformanceTestsAreNotSilentlySkipped(t *testing.T) {
	source := readExecutableTest(t)

	mockBody := functionBody(t, source, "mockExecutable")
	if !strings.Contains(mockBody, "t.Skip(") {
		t.Fatal("mockExecutable does not skip when the variable is unset, so a missing binary becomes an empty executable path")
	}
	if !strings.Contains(mockBody, "make test-conformance") {
		t.Fatal("mockExecutable does not name make test-conformance, so a reader cannot tell how to run the skipped case")
	}
	if !strings.Contains(mockBody, "mockExecutableEnvironment") {
		t.Fatal("mockExecutable does not read mockExecutableEnvironment")
	}

	requireBody := functionBody(t, source, "requireMock")
	if !strings.Contains(requireBody, "providerExecutableEnvironment") {
		t.Fatal("requireMock does not key its skip on providerExecutableEnvironment")
	}

	for _, name := range []string{"TestProviderDefaultConformance", "TestProviderUnsupportedFunction"} {
		body := functionBody(t, source, name)
		if strings.Contains(body, "t.Skip(") {
			t.Fatalf("%s skips on its own, so the conformance target cannot prove it ran", name)
		}
	}
}

// TestConformanceTargetSetsTheMockExecutable pins that the make target really
// sets the variable the two cases need, because without it they skip silently.
func TestConformanceTargetSetsTheMockExecutable(t *testing.T) {
	data, err := os.ReadFile(filepath.Join("..", "..", "Makefile"))
	if err != nil {
		t.Fatalf("read Makefile: %v", err)
	}
	recipe := makeRecipe(t, string(data), "test-conformance")
	if recipe == "" {
		t.Fatal("Makefile has no test-conformance recipe")
	}

	if !strings.Contains(recipe, "AGENT_CLUSTER_MOCK_EXECUTABLE=") {
		t.Fatal("the test-conformance recipe does not set AGENT_CLUSTER_MOCK_EXECUTABLE, so the conformance cases skip")
	}
	if !strings.Contains(recipe, "./internal/providerconformance") {
		t.Fatal("the test-conformance recipe does not run ./internal/providerconformance")
	}
	if !strings.Contains(recipe, "providers/mock") {
		t.Fatal("the test-conformance recipe does not build the Mock Provider module")
	}
}

// TestConformanceTargetReportsNoSkips runs the two cases through the real
// conformance target and requires both to pass with no skip. This is the only
// assertion that proves the cases execute rather than skip.
func TestConformanceTargetReportsNoSkips(t *testing.T) {
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
		"-run", "^(TestProviderDefaultConformance|TestProviderUnsupportedFunction)$",
		"./internal/providerconformance")
	run.Dir = filepath.Join("..", "..")
	run.Env = append(withoutVariable(os.Environ(), providerExecutableEnvironment),
		mockExecutableEnvironment+"="+binary)
	output, err := run.CombinedOutput()
	if err != nil {
		t.Fatalf("run the conformance cases: %v\n%s", err, output)
	}

	text := string(output)
	if strings.Contains(text, "--- SKIP") {
		t.Fatalf("a conformance case skipped even with the Mock Provider set:\n%s", text)
	}
	for _, name := range []string{"TestProviderDefaultConformance", "TestProviderUnsupportedFunction"} {
		if !strings.Contains(text, "--- PASS: "+name) {
			t.Fatalf("%s did not pass under the conformance target:\n%s", name, text)
		}
	}
}

// withoutVariable returns env with every assignment of name removed.
func withoutVariable(env []string, name string) []string {
	prefix := name + "="
	kept := make([]string, 0, len(env))
	for _, entry := range env {
		if strings.HasPrefix(entry, prefix) {
			continue
		}
		kept = append(kept, entry)
	}
	return kept
}
