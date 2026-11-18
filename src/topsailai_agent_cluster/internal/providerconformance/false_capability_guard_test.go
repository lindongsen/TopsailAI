package providerconformance

import (
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
)

// TestFalseCapabilityTestAssertsTheContradiction pins that the dedicated test
// proves the contradiction rather than merely observing an error: the descriptor
// must advertise the query, and the query must then be rejected with the
// provider's own "unsupported" code.
func TestFalseCapabilityTestAssertsTheContradiction(t *testing.T) {
	source := readExecutableTest(t)
	body := functionBody(t, source, "TestMockProviderFalseCapabilityIsDetected")

	// The advertised side: the test must read the descriptor and require the
	// query to be present, otherwise a fixture that never advertised it would
	// make the rejection meaningless.
	if !strings.Contains(body, "descriptor.Queries") {
		t.Fatal("the test does not read the advertised query list, so it cannot prove the query was advertised")
	}
	if !strings.Contains(body, "providercli.QueryModelCatalog") {
		t.Fatal("the test does not name the advertised query")
	}
	if !strings.Contains(body, `t.Fatal("fixture did not advertise model.catalog")`) {
		t.Fatal("the test does not fail when the fixture failed to advertise the query, so a silent fixture would pass")
	}

	// The rejected side: the response must be a failure carrying the provider's
	// own "unsupported" code. Accepting any error would let a broken provider
	// satisfy a capability-gap test.
	if !strings.Contains(body, `response.Error.Code != "unsupported"`) {
		t.Fatal("the test does not require the provider's own unsupported code, so any error would satisfy it")
	}
	if !strings.Contains(body, "response.OK ||") {
		t.Fatal("the test does not require the response to be a failure")
	}
}

// TestMockAdvertisesTheQueryItThenRejects pins the fixture side. The mock must
// advertise model.catalog unconditionally in its descriptor and reject it only
// when the false-capability fault is selected, so the contradiction is produced
// by the fault rather than by a descriptor that never listed the query.
func TestMockAdvertisesTheQueryItThenRejects(t *testing.T) {
	descriptor, err := os.ReadFile(filepath.Join("..", "..", "providers", "mock", "src", "main.go"))
	if err != nil {
		t.Fatalf("read the mock source: %v", err)
	}
	text := string(descriptor)

	// The descriptor must list the query in the unconditional query table.
	advertised := false
	for _, line := range strings.Split(text, "\n") {
		if strings.Contains(line, "{Name: queryModelCatalog, Version: \"v1\"}") {
			advertised = true
		}
	}
	if !advertised {
		t.Fatal("the mock descriptor does not advertise model.catalog, so the false-capability fault cannot produce a contradiction")
	}

	// The rejection must be gated on the fault, not applied to every query.
	if !strings.Contains(text, `fault == "false-capability"`) {
		t.Fatal("the mock does not gate the query rejection on the false-capability fault")
	}
	if !strings.Contains(text, `failureResponse(request.RequestID, "unsupported", "query is unsupported", "not_applied")`) {
		t.Fatal("the mock does not answer the false-capability fault with the provider's own unsupported code")
	}

	// The rejection must sit in the query branch, so a describe call still
	// advertises the query the query branch then refuses.
	queryIndex := strings.Index(text, "case functionQuery:")
	rejectIndex := strings.Index(text, `fault == "false-capability"`)
	if queryIndex < 0 || rejectIndex < 0 || rejectIndex < queryIndex {
		t.Fatal("the false-capability rejection is not inside the query branch")
	}
}

// TestFalseCapabilityTestIsNotSilentlySkipped pins that the test really runs
// under the conformance target. A skip would leave the row unproven while the
// package still reported PASS.
func TestFalseCapabilityTestIsNotSilentlySkipped(t *testing.T) {
	source := readExecutableTest(t)
	body := functionBody(t, source, "TestMockProviderFalseCapabilityIsDetected")

	if !strings.Contains(body, "requireMock(t)") {
		t.Fatal("the test does not call requireMock, so it may run without a Provider executable")
	}
	if strings.Contains(body, "testing.Short()") {
		t.Fatal("the test is gated on testing.Short(), so a short run silently drops the false-capability case")
	}
	// requireMock is the only permitted skip route, because it is the one that
	// names the reason. Any other t.Skip in the body would drop the case while
	// the package still reported PASS.
	if strings.Contains(body, "t.Skip(") {
		t.Fatal("the test skips itself, so the false-capability case can be dropped while the package still reports PASS")
	}

	// Two different skips exist and they must stay distinguishable. The skip that
	// fires when no Provider is configured comes from mockExecutable, so that
	// helper must name the target an operator has to run. requireMock guards the
	// opposite case, a real Provider being substituted, and its message must name
	// that variable instead of the target.
	mockHelper := functionBody(t, source, "mockExecutable")
	if !strings.Contains(mockHelper, "make test-conformance") {
		t.Fatal("mockExecutable does not name make test-conformance, so a skip gives no route to the real run")
	}
	if !strings.Contains(mockHelper, "t.Skip") {
		t.Fatal("mockExecutable does not skip when the Mock Provider is unset, so the case would run against an empty path")
	}

	requireHelper := functionBody(t, source, "requireMock")
	if !strings.Contains(requireHelper, "t.Skip") {
		t.Fatal("requireMock does not skip when another Provider is selected, so the mock-only fault would run against it")
	}
	// The source text carries the identifier, not the constant's value, so the
	// check must look for the identifier spelling.
	if !strings.Contains(requireHelper, "providerExecutableEnvironment") {
		t.Fatal("requireMock does not name the variable that selects another Provider, so its skip is indistinguishable from a missing Mock Provider")
	}
}

// TestFalseCapabilityReallyRunsUnderTheConformanceTarget builds the Mock
// Provider and runs the case through a nested test binary. This is the only
// assertion that proves the case executes rather than skips.
func TestFalseCapabilityReallyRunsUnderTheConformanceTarget(t *testing.T) {
	if testing.Short() {
		t.Skip("builds the Mock Provider and runs a nested test binary")
	}

	moduleDir := filepath.Join("..", "..", "providers", "mock")
	binary := filepath.Join(t.TempDir(), "agent-cluster-provider-mock")

	build := exec.Command("go", "build", "-o", binary, "./src")
	build.Dir = moduleDir
	if output, err := build.CombinedOutput(); err != nil {
		t.Fatalf("build the Mock Provider: %v\n%s", err, output)
	}

	run := exec.Command("go", "test", "-count=1", "-v",
		"-run", "^TestMockProviderFalseCapabilityIsDetected$",
		"./internal/providerconformance")
	run.Dir = filepath.Join("..", "..")
	run.Env = append(withoutVariable(os.Environ(), providerExecutableEnvironment),
		mockExecutableEnvironment+"="+binary)
	output, err := run.CombinedOutput()
	if err != nil {
		t.Fatalf("run the false-capability case: %v\n%s", err, output)
	}

	text := string(output)
	if strings.Contains(text, "--- SKIP") {
		t.Fatalf("the false-capability case skipped even with the Mock Provider set:\n%s", text)
	}
	if !strings.Contains(text, "--- PASS: TestMockProviderFalseCapabilityIsDetected") {
		t.Fatalf("the false-capability case did not pass:\n%s", text)
	}
}
