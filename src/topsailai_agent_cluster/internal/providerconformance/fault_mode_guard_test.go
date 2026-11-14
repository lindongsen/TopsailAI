package providerconformance

import (
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"strings"
	"testing"
)

// faultEntry is one row of a fault table: the injected fault and the error text
// the test requires.
type faultEntry struct {
	fault string
	match string
}

// faultEntryPattern matches one table row such as
// `{fault: "malformed-json", match: "decode provider response"},`.
var faultEntryPattern = regexp.MustCompile(`\{fault: "([^"]+)", match: "([^"]+)"\}`)

// faultTable returns the rows of the fault table declared inside one test body.
func faultTable(t *testing.T, body, name string) []faultEntry {
	t.Helper()
	matches := faultEntryPattern.FindAllStringSubmatch(body, -1)
	if len(matches) == 0 {
		t.Fatalf("%s declares no fault table rows", name)
	}
	entries := make([]faultEntry, 0, len(matches))
	for _, match := range matches {
		entries = append(entries, faultEntry{fault: match[1], match: match[2]})
	}
	return entries
}

// faultMatch returns the required error text for one fault, and reports whether
// the fault is present at all.
func faultMatch(entries []faultEntry, fault string) (string, bool) {
	for _, entry := range entries {
		if entry.fault == fault {
			return entry.match, true
		}
	}
	return "", false
}

// TestEveryFaultModeHasADedicatedAssertion pins the five modes the acceptance
// row names to the concrete subtest and error text that carry each one. A mode
// with no row would be a mode the suite never exercises.
func TestEveryFaultModeHasADedicatedAssertion(t *testing.T) {
	source := readExecutableTest(t)
	protocolBody := functionBody(t, source, "TestMockProviderProtocolFaults")
	streamBody := functionBody(t, source, "TestMockProviderStreamFaults")

	protocolEntries := faultTable(t, protocolBody, "TestMockProviderProtocolFaults")
	streamEntries := faultTable(t, streamBody, "TestMockProviderStreamFaults")

	// malformed JSON: the response cannot be decoded at all.
	if match, ok := faultMatch(protocolEntries, "malformed-json"); !ok {
		t.Fatal("no fault row covers malformed JSON")
	} else if match != "decode provider response" {
		t.Fatalf("malformed-json requires %q, so a decode failure with different text would pass", match)
	}

	// extra output: a second JSON document, or a banner before the document.
	if match, ok := faultMatch(protocolEntries, "duplicate-response"); !ok {
		t.Fatal("no fault row covers extra output after the response document")
	} else if match != "extra JSON document" {
		t.Fatalf("duplicate-response requires %q", match)
	}
	if match, ok := faultMatch(protocolEntries, "stdout-banner"); !ok {
		t.Fatal("no fault row covers extra output before the response document")
	} else if match != "invalid character" {
		t.Fatalf("stdout-banner requires %q", match)
	}

	// wrong correlation: a response or stream frame carrying another request id.
	if match, ok := faultMatch(protocolEntries, "wrong-request-id"); !ok {
		t.Fatal("no fault row covers a response with the wrong request id")
	} else if match != "does not match" {
		t.Fatalf("wrong-request-id requires %q", match)
	}
	if match, ok := faultMatch(streamEntries, "stream-correlation"); !ok {
		t.Fatal("no fault row covers a stream frame with the wrong correlation")
	} else if match != "does not match" {
		t.Fatalf("stream-correlation requires %q", match)
	}

	// timeout: the invocation deadline, and cancellation of the caller context.
	timeoutBody := functionBody(t, source, "TestMockProviderTimeoutAndCancellation")
	if !strings.Contains(timeoutBody, `"invocation deadline"`) {
		t.Fatal("TestMockProviderTimeoutAndCancellation does not require the invocation deadline error")
	}
	if !strings.Contains(timeoutBody, `"context canceled"`) {
		t.Fatal("TestMockProviderTimeoutAndCancellation does not require the cancellation error")
	}

	// output limit: stdout bytes, stream records, and stderr bytes.
	if match, ok := faultMatch(protocolEntries, "oversized-stdout"); !ok {
		t.Fatal("no fault row covers the stdout byte limit")
	} else if match != "stdout byte limit exceeded" {
		t.Fatalf("oversized-stdout requires %q", match)
	}
	if match, ok := faultMatch(streamEntries, "record-overflow"); !ok {
		t.Fatal("no fault row covers the stream record limit")
	} else if match != "record limit exceeded" {
		t.Fatalf("record-overflow requires %q", match)
	}
}

// TestFaultAssertionsRequireTheSpecificErrorText pins that every row compares
// the error text rather than accepting any error at all.
func TestFaultAssertionsRequireTheSpecificErrorText(t *testing.T) {
	source := readExecutableTest(t)

	for _, name := range []string{"TestMockProviderProtocolFaults", "TestMockProviderStreamFaults"} {
		body := functionBody(t, source, name)
		if !strings.Contains(body, "strings.Contains(err.Error(), testCase.match)") {
			t.Fatalf("%s does not compare the error text against the table row, so any error would satisfy it", name)
		}
		if !strings.Contains(body, "err == nil ||") {
			t.Fatalf("%s does not require an error at all", name)
		}
		for _, entry := range faultTable(t, body, name) {
			if strings.TrimSpace(entry.match) == "" {
				t.Fatalf("%s has a row for %q with an empty match, so any error would satisfy it", name, entry.fault)
			}
		}
	}
}

// TestRecordOverflowIsNotSkipped pins that the record limit case really runs.
// A skip would leave the output-limit mode unproven while the package still
// reports PASS.
func TestRecordOverflowIsNotSkipped(t *testing.T) {
	source := readExecutableTest(t)
	body := functionBody(t, source, "TestMockProviderStreamFaults")

	if _, ok := faultMatch(faultTable(t, body, "TestMockProviderStreamFaults"), "record-overflow"); !ok {
		t.Fatal("TestMockProviderStreamFaults no longer exercises record-overflow")
	}
	if strings.Contains(body, "t.Skip(") {
		t.Fatal("TestMockProviderStreamFaults skips, so the record limit case may never run")
	}
	if strings.Contains(body, "testing.Short()") {
		t.Fatal("TestMockProviderStreamFaults is gated on testing.Short(), so a short run silently drops the record limit case")
	}

	// The runner must enforce the limit, otherwise the mock frames would be
	// accepted and the case would pass for the wrong reason.
	runner, err := os.ReadFile("runner.go")
	if err != nil {
		t.Fatalf("read runner.go: %v", err)
	}
	if !strings.Contains(string(runner), "provider stream record limit exceeded") {
		t.Fatal("runner.go does not enforce the stream record limit")
	}
}

// TestStderrOverflowIsLabeledNotFailed pins what the stderr case proves. An
// oversized stderr stream is truncated and labelled, not treated as a failure,
// so the test must assert success plus the truncation flag rather than an error.
func TestStderrOverflowIsLabeledNotFailed(t *testing.T) {
	source := readExecutableTest(t)
	body := functionBody(t, source, "TestMockProviderStderrLimitIsLabeled")

	if !strings.Contains(body, "!response.OK") {
		t.Fatal("TestMockProviderStderrLimitIsLabeled does not require the response to succeed, so it may be asserting a failure instead of a labelled truncation")
	}
	if !strings.Contains(body, "invocation.StderrTruncated") {
		t.Fatal("TestMockProviderStderrLimitIsLabeled does not require the truncation flag")
	}
	if !strings.Contains(body, "runner.config.MaxStderrBytes") {
		t.Fatal("TestMockProviderStderrLimitIsLabeled does not require the retained bytes to equal the configured limit")
	}
	if strings.Contains(body, "err != nil") && !strings.Contains(body, "t.Fatal(err)") {
		t.Fatal("TestMockProviderStderrLimitIsLabeled treats a stderr overflow as an invocation error")
	}
}

// TestFaultModesReallyRunUnderTheConformanceTarget runs the four fault tests
// through a nested test binary and requires every subtest to pass with no skip.
// This is the only assertion that proves the modes execute rather than skip.
func TestFaultModesReallyRunUnderTheConformanceTarget(t *testing.T) {
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
		"-run", "^(TestMockProviderProtocolFaults|TestMockProviderStreamFaults|TestMockProviderTimeoutAndCancellation|TestMockProviderStderrLimitIsLabeled)$",
		"./internal/providerconformance")
	run.Dir = filepath.Join("..", "..")
	run.Env = append(withoutVariable(os.Environ(), providerExecutableEnvironment),
		mockExecutableEnvironment+"="+binary)
	output, err := run.CombinedOutput()
	if err != nil {
		t.Fatalf("run the fault tests: %v\n%s", err, output)
	}

	text := string(output)
	if strings.Contains(text, "--- SKIP") {
		t.Fatalf("a fault case skipped even with the Mock Provider set:\n%s", text)
	}

	passed := 0
	for _, line := range strings.Split(text, "\n") {
		if strings.HasPrefix(strings.TrimSpace(line), "--- PASS:") && strings.HasPrefix(line, " ") {
			passed++
		}
	}
	if passed != 15 {
		t.Fatalf("the fault tests reported %d passing subtests, want 15:\n%s", passed, text)
	}
}
