package providerconformance

import (
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
)

// streamFaultTestName is the conformance test that carries the five stream
// frame faults the acceptance row names.
const streamFaultTestName = "TestMockProviderStreamFaults"

// streamValidatorFile is the validator that must reject the malformed frames.
const streamValidatorFile = "stream.go"

// streamFaultExpectations pins each fault the acceptance row names to the error
// text the conformance suite requires. A fault with no row would be a fault the
// suite never exercises, and a row with an empty match would accept any error.
var streamFaultExpectations = map[string]string{
	"missing-terminal":     "stream_interrupted",
	"duplicate-terminal":   "after terminal",
	"post-terminal-record": "after terminal",
	"stream-correlation":   "does not match",
	"record-overflow":      "record limit exceeded",
}

// readStreamValidator returns the source of the stream validator.
func readStreamValidator(t *testing.T) string {
	t.Helper()
	data, err := os.ReadFile(filepath.Join("..", "providercli", streamValidatorFile))
	if err != nil {
		t.Fatalf("read %s: %v", streamValidatorFile, err)
	}
	return string(data)
}

// TestEveryStreamFaultHasADedicatedAssertion pins the five faults the
// acceptance row names to the concrete subtest and error text that carry each
// one. The row names missing, duplicate and post-terminal frames explicitly, so
// a table that dropped one of them would leave the row unproven.
func TestEveryStreamFaultHasADedicatedAssertion(t *testing.T) {
	source := readExecutableTest(t)
	body := functionBody(t, source, streamFaultTestName)
	entries := faultTable(t, body, streamFaultTestName)

	for fault, want := range streamFaultExpectations {
		match, ok := faultMatch(entries, fault)
		if !ok {
			t.Fatalf("%s declares no row for the %q fault", streamFaultTestName, fault)
		}
		if match != want {
			t.Fatalf("the %q fault requires %q, want %q", fault, match, want)
		}
	}
	if len(entries) != len(streamFaultExpectations) {
		t.Fatalf("%s declares %d rows, want %d", streamFaultTestName, len(entries), len(streamFaultExpectations))
	}
}

// TestStreamFaultsRequireTheSpecificErrorText pins that every row is compared
// against the error text rather than merely requiring an error. A row that only
// required err != nil would pass on any failure, including a crash.
func TestStreamFaultsRequireTheSpecificErrorText(t *testing.T) {
	source := readExecutableTest(t)
	body := functionBody(t, source, streamFaultTestName)

	if !strings.Contains(body, "err == nil ||") {
		t.Fatal("the stream fault test does not reject a nil error before comparing the text")
	}
	if !strings.Contains(body, "strings.Contains(err.Error(), testCase.match)") {
		t.Fatal("the stream fault test does not compare the error text against the row")
	}
	for _, entry := range faultTable(t, body, streamFaultTestName) {
		if strings.TrimSpace(entry.match) == "" {
			t.Fatalf("the %q fault declares an empty match, so any error would satisfy it", entry.fault)
		}
	}
}

// TestDuplicateAndPostTerminalShareOneMessage records a real limitation rather
// than hiding it: a second terminal frame and a record after the terminal frame
// are both rejected with "after terminal", so the error text alone cannot tell
// them apart. What the suite does prove is that the validator rejects any frame
// after the terminal frame before it inspects the sequence number, which is the
// ordering that makes both faults fail for the intended reason.
func TestDuplicateAndPostTerminalShareOneMessage(t *testing.T) {
	source := readExecutableTest(t)
	entries := faultTable(t, functionBody(t, source, streamFaultTestName), streamFaultTestName)

	duplicate, ok := faultMatch(entries, "duplicate-terminal")
	if !ok {
		t.Fatal("the duplicate-terminal fault is missing")
	}
	postTerminal, ok := faultMatch(entries, "post-terminal-record")
	if !ok {
		t.Fatal("the post-terminal-record fault is missing")
	}
	if duplicate != postTerminal {
		t.Fatalf("the two faults no longer share one message (%q vs %q); update this guard and the evidence", duplicate, postTerminal)
	}

	validator := readStreamValidator(t)
	ended := strings.Index(validator, "if v.ended {")
	if ended < 0 {
		t.Fatal("the validator does not reject a frame after the terminal frame")
	}
	sequence := strings.Index(validator, "if frame.Sequence != v.lastSequence+1 {")
	if sequence < 0 {
		t.Fatal("the validator does not check the frame sequence")
	}
	if ended > sequence {
		t.Fatal("the validator checks the sequence before the terminal state, so a post-terminal frame would be rejected for the wrong reason")
	}
	if !strings.Contains(validator, "stream frame received after terminal frame") {
		t.Fatal("the validator does not report a frame after the terminal frame")
	}
	if !strings.Contains(validator, "stream_interrupted: EOF before terminal frame") {
		t.Fatal("the validator does not report a stream that ended without a terminal frame")
	}
}

// TestStreamFaultsAreNotSilentlySkipped pins the skip path. The whole test
// skips unless the Mock Provider is configured, so a plain package run reports
// PASS while proving nothing; the guard must pin that the skip is explicit and
// that the test itself never skips a case.
func TestStreamFaultsAreNotSilentlySkipped(t *testing.T) {
	source := readExecutableTest(t)
	body := functionBody(t, source, streamFaultTestName)

	if !strings.Contains(body, "requireMock(t)") {
		t.Fatal("the stream fault test does not require the Mock Provider")
	}
	if strings.Contains(body, "t.Skip(") {
		t.Fatal("the stream fault test skips a case instead of asserting it")
	}
	if strings.Contains(body, "testing.Short()") {
		t.Fatal("the stream fault test is skipped in short mode")
	}

	helper := functionBody(t, source, "mockExecutable")
	if !strings.Contains(helper, "make test-conformance") {
		t.Fatal("the skip message does not name the target that sets the Mock Provider")
	}
}

// TestStreamFaultsReallyRunUnderTheConformanceTarget runs the stream fault test
// through a nested test binary and requires every subtest to pass with no skip.
// This is the only assertion that proves the five faults execute rather than
// skip, because a plain package run reports PASS with five SKIP lines.
func TestStreamFaultsReallyRunUnderTheConformanceTarget(t *testing.T) {
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

	run := exec.Command("go", "test", "-count=1", "-v", "-run", "^"+streamFaultTestName+"$", "./internal/providerconformance")
	run.Dir = filepath.Join("..", "..")
	run.Env = append(withoutVariable(os.Environ(), providerExecutableEnvironment),
		mockExecutableEnvironment+"="+binary)
	output, err := run.CombinedOutput()
	if err != nil {
		t.Fatalf("run the stream fault test: %v\n%s", err, output)
	}

	text := string(output)
	if strings.Contains(text, "--- SKIP") {
		t.Fatalf("a stream fault case skipped even with the Mock Provider set:\n%s", text)
	}

	passed := 0
	for _, line := range strings.Split(text, "\n") {
		if strings.HasPrefix(line, " ") && strings.HasPrefix(strings.TrimSpace(line), "--- PASS:") {
			passed++
		}
	}
	if passed != len(streamFaultExpectations) {
		t.Fatalf("the stream fault test reported %d passing subtests, want %d:\n%s", passed, len(streamFaultExpectations), text)
	}
}
