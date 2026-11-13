package packaging_test

import (
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

// ctlReplaceHelper is the stand-in Endpoint the controller signals.
//
// It ignores SIGHUP and answers with a document whose request ID is copied from
// the request the controller wrote, so the controller's correlation check is
// exercised against a real answer instead of a fixture the test guessed. The mode
// selects the answer shape: "reject" reports a refused activation, "mismatch"
// reports an answer for a different request.
const ctlReplaceHelper = `#!/bin/bash
trap 'answer' HUP
answer() {
    local rid
    rid=$(sed -n 's/.*"request_id"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "${REQUEST_FILE}" | head -n 1)
    rm -f "${REQUEST_FILE}"
    if [ "${MODE}" = "mismatch" ]; then
        rid="wrong-request-id"
    fi
    printf '{"request_id":"%s","ok":false,"error":"candidate is not executable"}\n' "${rid}" >"${RESULT_FILE}"
}
while :; do sleep 0.1; done
`

// ctlReplaceBundle is one throwaway node bundle with the controller installed.
type ctlReplaceBundle struct {
	dir, ctl, config, requestFile, resultFile, pidFile string
}

// newCtlReplaceBundle copies the controller into a temporary bundle and writes a
// role configuration, so the test exercises the shipped script rather than a
// reimplementation of it.
func newCtlReplaceBundle(t *testing.T, role string, replaceRequestFile string) *ctlReplaceBundle {
	t.Helper()
	dir := t.TempDir()
	ctl := filepath.Join(dir, "agent-clusterctl")
	source, err := os.ReadFile(filepath.Join("..", "..", "scripts", "agent-clusterctl"))
	if err != nil {
		t.Fatalf("read the controller: %v", err)
	}
	if err := os.WriteFile(ctl, source, 0o755); err != nil {
		t.Fatal(err)
	}
	configDir := filepath.Join(dir, "conf", role)
	if err := os.MkdirAll(configDir, 0o755); err != nil {
		t.Fatal(err)
	}
	for _, sub := range []string{"run", "logs", "data", "certs"} {
		if err := os.MkdirAll(filepath.Join(dir, sub), 0o755); err != nil {
			t.Fatal(err)
		}
	}
	config := filepath.Join(configDir, "node.conf")
	lines := []string{
		"ROLE=" + role,
		"PID_FILE=../../run/" + role + ".pid",
		"LOG_PATH=../../logs/" + role + ".log",
		"DATABASE_PATH=../../data/" + role + ".sqlite",
		"TLS_CA_FILE=../../certs/ca.pem",
		"TLS_CERTIFICATE_FILE=../../certs/node.pem",
		"TLS_KEY_FILE=../../certs/node-key.pem",
	}
	if replaceRequestFile != "" {
		lines = append(lines, "REPLACE_REQUEST_FILE="+replaceRequestFile)
	}
	if err := os.WriteFile(config, []byte(strings.Join(lines, "\n")+"\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	return &ctlReplaceBundle{
		dir: dir, ctl: ctl, config: config,
		requestFile: filepath.Join(dir, "run", "replace-request.json"),
		resultFile:  filepath.Join(dir, "run", "replace-result.json"),
		pidFile:     filepath.Join(dir, "run", role+".pid"),
	}
}

// run executes one controller action and returns its combined output and exit code.
func (b *ctlReplaceBundle) run(t *testing.T, args ...string) (string, int) {
	t.Helper()
	cmd := exec.Command(b.ctl, append([]string{"-c", b.config}, args...)...)
	cmd.Dir = b.dir
	output, err := cmd.CombinedOutput()
	code := 0
	if err != nil {
		exitErr, ok := err.(*exec.ExitError)
		if !ok {
			t.Fatalf("run the controller: %v", err)
		}
		code = exitErr.ExitCode()
	}
	return string(output), code
}

// startHelper starts the stand-in Endpoint and records its pid, so the controller
// finds a live process to signal.
func (b *ctlReplaceBundle) startHelper(t *testing.T, mode string) {
	t.Helper()
	helper := filepath.Join(b.dir, "helper.sh")
	if err := os.WriteFile(helper, []byte(ctlReplaceHelper), 0o755); err != nil {
		t.Fatal(err)
	}
	cmd := exec.Command(helper)
	cmd.Dir = b.dir
	cmd.Env = append(os.Environ(),
		"MODE="+mode,
		"REQUEST_FILE="+b.requestFile,
		"RESULT_FILE="+b.resultFile,
	)
	if err := cmd.Start(); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() {
		_ = cmd.Process.Kill()
		_, _ = cmd.Process.Wait()
	})
	if err := os.WriteFile(b.pidFile, []byte(strings.TrimSpace(itoa(cmd.Process.Pid))+"\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	// The helper installs its SIGHUP trap after the shell starts, so a signal sent
	// immediately would kill it before the trap exists and the test would assert a
	// dead process instead of the controller's behaviour.
	time.Sleep(300 * time.Millisecond)
}

// itoa formats a pid without importing strconv for one call.
func itoa(value int) string {
	if value == 0 {
		return "0"
	}
	digits := make([]byte, 0, 8)
	for value > 0 {
		digits = append([]byte{byte('0' + value%10)}, digits...)
		value /= 10
	}
	return string(digits)
}

// TestCtlReplaceRefusesIncompleteRequests proves the controller rejects an
// incomplete request before it writes a document or signals a process.
func TestCtlReplaceRefusesIncompleteRequests(t *testing.T) {
	cases := []struct {
		name string
		args []string
		want string
	}{
		{name: "missing adapter", args: []string{"replace", "--executable", "/bin/true"}, want: "replace requires --adapter"},
		{name: "missing executable", args: []string{"replace", "--adapter", "mock-main"}, want: "replace requires --executable"},
	}
	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			bundle := newCtlReplaceBundle(t, "endpoint", "../../run/replace-request.json")
			bundle.startHelper(t, "reject")
			output, code := bundle.run(t, testCase.args...)
			if code == 0 {
				t.Fatalf("controller accepted an incomplete request: %s", output)
			}
			if !strings.Contains(output, testCase.want) {
				t.Fatalf("output does not name the missing option %q: %s", testCase.want, output)
			}
			// Nothing may be written when the request is incomplete, because a
			// half-formed document would be consumed by the next signal.
			if _, err := os.Stat(bundle.requestFile); !os.IsNotExist(err) {
				t.Fatalf("an incomplete request still wrote %s", bundle.requestFile)
			}
		})
	}
}

// TestCtlReplaceRefusesUnconfiguredRequestFile proves activation is fail-closed
// on a node that names no request file.
func TestCtlReplaceRefusesUnconfiguredRequestFile(t *testing.T) {
	bundle := newCtlReplaceBundle(t, "endpoint", "")
	bundle.startHelper(t, "reject")
	output, code := bundle.run(t, "replace", "--adapter", "mock-main", "--executable", "/bin/true")
	if code == 0 {
		t.Fatalf("controller activated on a node with no request file: %s", output)
	}
	if !strings.Contains(output, "REPLACE_REQUEST_FILE is not configured") {
		t.Fatalf("output does not report the fail-closed default: %s", output)
	}
}

// TestCtlReplaceRefusesServerRole proves activation is an Endpoint-only action.
func TestCtlReplaceRefusesServerRole(t *testing.T) {
	bundle := newCtlReplaceBundle(t, "server", "../../run/replace-request.json")
	bundle.startHelper(t, "reject")
	output, code := bundle.run(t, "replace", "--adapter", "mock-main", "--executable", "/bin/true")
	if code == 0 {
		t.Fatalf("controller activated on the server role: %s", output)
	}
	if !strings.Contains(output, "replace applies to the endpoint role only") {
		t.Fatalf("output does not report the role restriction: %s", output)
	}
}

// TestCtlReplaceRemovesStaleResult proves an answer from an earlier activation is
// discarded instead of being read as this one's outcome.
func TestCtlReplaceRemovesStaleResult(t *testing.T) {
	bundle := newCtlReplaceBundle(t, "endpoint", "../../run/replace-request.json")
	bundle.startHelper(t, "reject")
	stale := `{"request_id":"stale-request","ok":true,"result":{"effective_version":"9.9.9"}}`
	if err := os.WriteFile(bundle.resultFile, []byte(stale), 0o644); err != nil {
		t.Fatal(err)
	}
	output, _ := bundle.run(t, "replace", "--adapter", "mock-main", "--executable", "/bin/true")
	if !strings.Contains(output, "removed stale result") {
		t.Fatalf("controller did not report removing the stale answer: %s", output)
	}
	// The stale answer claimed success. A controller that read it would report an
	// activation, so the absence of that claim is the property under test.
	if strings.Contains(output, "activated mock-main on 9.9.9") {
		t.Fatalf("controller read the stale answer as its own outcome: %s", output)
	}
}

// TestCtlReplaceRejectsUncorrelatedAnswer proves an answer for a different
// request is refused rather than reported as this activation's result.
func TestCtlReplaceRejectsUncorrelatedAnswer(t *testing.T) {
	bundle := newCtlReplaceBundle(t, "endpoint", "../../run/replace-request.json")
	bundle.startHelper(t, "mismatch")
	output, code := bundle.run(t, "replace", "--adapter", "mock-main", "--executable", "/bin/true")
	if code == 0 {
		t.Fatalf("controller accepted an uncorrelated answer: %s", output)
	}
	if !strings.Contains(output, "does not match request") {
		t.Fatalf("output does not report the correlation failure: %s", output)
	}
}

// TestCtlReplaceReportsRejectionWithNonZeroExit proves a refused activation is
// reported as a failure, so a scripted caller cannot read it as success.
func TestCtlReplaceReportsRejectionWithNonZeroExit(t *testing.T) {
	bundle := newCtlReplaceBundle(t, "endpoint", "../../run/replace-request.json")
	bundle.startHelper(t, "reject")
	output, code := bundle.run(t, "replace", "--adapter", "mock-main", "--executable", "/bin/true")
	if code == 0 {
		t.Fatalf("controller exited zero for a refused activation: %s", output)
	}
	if !strings.Contains(output, "activation rejected") {
		t.Fatalf("output does not report the rejection: %s", output)
	}
	if !strings.Contains(output, "candidate is not executable") {
		t.Fatalf("output does not carry the reason the Endpoint reported: %s", output)
	}
	// The request must have been written and signalled, otherwise the rejection
	// came from the controller instead of from the Endpoint.
	if _, err := os.Stat(bundle.requestFile); !os.IsNotExist(err) {
		t.Fatalf("the request document was not consumed: %v", err)
	}
}
