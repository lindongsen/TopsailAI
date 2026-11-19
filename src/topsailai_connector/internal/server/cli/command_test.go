package cli

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"topsailai_connector/internal/protocol"
	"topsailai_connector/internal/security"
)

// environment builds a lookup function from a map, so a test never mutates process
// state.
func environment(values map[string]string) func(string) string {
	return func(name string) string { return values[name] }
}

// readEnvelope is a success answer for file.read.
const readEnvelope = `{"code":0,"message":"success","data":{"content":"aGVsbG8=","size":5,"truncated":false},"request_id":"req_1","timestamp":1700000000000}`

// listEnvelope is a success answer for file.list.
const listEnvelope = `{"code":0,"message":"success","data":{"entries":[{"name":"a.txt","type":"file","size":5,"mode":"-rw-r--r--","modified_at":1700000000000},{"name":"b","type":"dir","size":0,"mode":"drwxr-xr-x","modified_at":1700000001000}]},"request_id":"req_2","timestamp":1700000000000}`

// statEnvelope is a success answer for file.stat.
const statEnvelope = `{"code":0,"message":"success","data":{"name":"a.txt","type":"file","size":5,"mode":"-rw-r--r--","modified_at":1700000000000,"is_symlink":false},"request_id":"req_3","timestamp":1700000000000}`

// statSymlinkEnvelope is a stat answer for a symlink.
const statSymlinkEnvelope = `{"code":0,"message":"success","data":{"name":"link","type":"symlink","size":7,"mode":"Lrwxrwxrwx","modified_at":1700000000000,"is_symlink":true,"link_target":"a.txt"},"request_id":"req_4","timestamp":1700000000000}`

// refusalEnvelope is a refusal answer.
const refusalEnvelope = `{"code":1005,"message":"denied","data":null,"request_id":"req_5","timestamp":1700000000000}`

// runFixture is one CLI invocation and its captured output.
type runFixture struct {
	status int
	stdout string
	stderr string
}

// runCLI executes one invocation against a server that answers with a fixed body.
func runCLI(t *testing.T, status int, response string, arguments []string, values map[string]string) runFixture {
	t.Helper()

	server := httptest.NewServer(http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
		writer.Header().Set("Content-Type", "application/json")
		writer.WriteHeader(status)
		if _, err := writer.Write([]byte(response)); err != nil {
			t.Errorf("write response: %v", err)
		}
	}))
	t.Cleanup(server.Close)

	// The server URL is injected through the environment so the flag surface stays
	// exactly what an operator types.
	merged := map[string]string{EnvServerURL: server.URL}
	for name, value := range values {
		merged[name] = value
	}

	var stdout, stderr bytes.Buffer
	status = Run(arguments, environment(merged), &stdout, &stderr)
	return runFixture{status: status, stdout: stdout.String(), stderr: stderr.String()}
}

// validArguments returns arguments that pass every local check.
func validArguments(t *testing.T) []string {
	t.Helper()
	return []string{
		"--client-credential", testClientCredential().String(),
		"--node-credential", testNodeCredential().String(),
		"--node-id", testNodeID(t),
		"--scope", "project",
		"--path", "a.txt",
		"file.read",
	}
}

// TestRunRefusesMissingConfiguration proves every required value is reported as a
// usage error with a non-zero status.
func TestRunRefusesMissingConfiguration(t *testing.T) {
	clientCredential := testClientCredential().String()
	nodeCredential := testNodeCredential().String()
	nodeID := testNodeID(t)

	cases := map[string][]string{
		"no operation":                {"--client-credential", clientCredential, "--node-credential", nodeCredential, "--node-id", nodeID, "--scope", "project"},
		"no client credential":        {"--node-credential", nodeCredential, "--node-id", nodeID, "--scope", "project", "file.read"},
		"no node credential":          {"--client-credential", clientCredential, "--node-id", nodeID, "--scope", "project", "file.read"},
		"no node id":                  {"--client-credential", clientCredential, "--node-credential", nodeCredential, "--scope", "project", "file.read"},
		"no scope":                    {"--client-credential", clientCredential, "--node-credential", nodeCredential, "--node-id", nodeID, "file.read"},
		"two operations":              {"--client-credential", clientCredential, "--node-credential", nodeCredential, "--node-id", nodeID, "--scope", "project", "file.read", "file.list"},
		"unknown operation":           {"--client-credential", clientCredential, "--node-credential", nodeCredential, "--node-id", nodeID, "--scope", "project", "file.delete"},
		"negative offset":             {"--client-credential", clientCredential, "--node-credential", nodeCredential, "--node-id", nodeID, "--scope", "project", "--offset", "-1", "file.read"},
		"negative length":             {"--client-credential", clientCredential, "--node-credential", nodeCredential, "--node-id", nodeID, "--scope", "project", "--length", "-1", "file.read"},
		"unknown flag":                {"--client-credential", clientCredential, "--node-credential", nodeCredential, "--node-id", nodeID, "--scope", "project", "--nope", "file.read"},
		"malformed client credential": {"--client-credential", "no-dot", "--node-credential", nodeCredential, "--node-id", nodeID, "--scope", "project", "file.read"},
		"malformed node credential":   {"--client-credential", clientCredential, "--node-credential", "no-dot", "--node-id", nodeID, "--scope", "project", "file.read"},
		"malformed node id":           {"--client-credential", clientCredential, "--node-credential", nodeCredential, "--node-id", "abc", "--scope", "project", "file.read"},
	}

	for name, arguments := range cases {
		t.Run(name, func(t *testing.T) {
			result := runCLI(t, http.StatusOK, readEnvelope, arguments, nil)

			// The status and the message are asserted as a pair, because each one alone
			// passes while the combination is wrong. A refusal that prints `usage:` and
			// exits 1 leaves a script unable to tell "the command line was rejected" from
			// "the request ran and failed", and an assertion of `status != 0` cannot see
			// that. Every case here is refused before anything is sent, so every case
			// must exit 2.
			if result.status != 2 {
				t.Errorf("status = %d, want 2", result.status)
			}
			if result.stdout != "" {
				t.Errorf("stdout = %q, want empty", result.stdout)
			}
			if !strings.Contains(result.stderr, "usage:") {
				t.Errorf("stderr = %q, want a message containing %q", result.stderr, "usage:")
			}
		})
	}
}

// TestRunRefusesAMissingServerURL proves an unset server URL is a usage error rather
// than a request to an empty host.
func TestRunRefusesAMissingServerURL(t *testing.T) {
	arguments := validArguments(t)

	var stdout, stderr bytes.Buffer
	status := Run(arguments, environment(nil), &stdout, &stderr)

	if status == 0 {
		t.Error("status = 0, want non-zero")
	}
	if !strings.Contains(stderr.String(), EnvServerURL) {
		t.Errorf("stderr = %q, want it to name %s", stderr.String(), EnvServerURL)
	}
}

// TestRunReadsTheEnvironment proves the documented variables are honoured, so a script
// can export them instead of repeating flags.
func TestRunReadsTheEnvironment(t *testing.T) {
	result := runCLI(t, http.StatusOK, readEnvelope, []string{"--scope", "project", "--path", "a.txt", "file.read"}, map[string]string{
		EnvClientCredential: testClientCredential().String(),
		EnvNodeCredential:   testNodeCredential().String(),
		EnvNodeID:           testNodeID(t),
	})

	if result.status != 0 {
		t.Fatalf("status = %d, stderr = %q", result.status, result.stderr)
	}
	if result.stdout != "hello" {
		t.Errorf("stdout = %q, want hello", result.stdout)
	}
}

// TestRunFlagsOverrideTheEnvironment proves a flag is the more explicit statement of
// intent.
func TestRunFlagsOverrideTheEnvironment(t *testing.T) {
	// The environment carries a malformed node credential; the flag carries a valid
	// one. If the environment won, the request would be refused locally.
	result := runCLI(t, http.StatusOK, readEnvelope, []string{
		"--node-credential", testNodeCredential().String(),
		"--node-id", testNodeID(t),
		"--scope", "project",
		"--path", "a.txt",
		"file.read",
	}, map[string]string{
		EnvClientCredential: testClientCredential().String(),
		EnvNodeCredential:   "malformed",
	})

	if result.status != 0 {
		t.Fatalf("status = %d, stderr = %q", result.status, result.stderr)
	}
}

// TestRunWritesRawBytesForRead proves a read payload is written as raw bytes so it can
// be piped.
func TestRunWritesRawBytesForRead(t *testing.T) {
	result := runCLI(t, http.StatusOK, readEnvelope, validArguments(t), nil)

	if result.status != 0 {
		t.Fatalf("status = %d, stderr = %q", result.status, result.stderr)
	}
	if result.stdout != "hello" {
		t.Errorf("stdout = %q, want hello", result.stdout)
	}
	if result.stderr != "" {
		t.Errorf("stderr = %q, want empty", result.stderr)
	}
}

// TestRunReportsTruncationOnStderr proves a truncated read is noticed on the notice
// stream, because a notice on stdout would corrupt a piped payload.
func TestRunReportsTruncationOnStderr(t *testing.T) {
	truncated := `{"code":0,"message":"success","data":{"content":"aGVsbG8=","size":5,"truncated":true},"request_id":"req_1","timestamp":1700000000000}`

	result := runCLI(t, http.StatusOK, truncated, validArguments(t), nil)

	if result.status != 0 {
		t.Fatalf("status = %d, stderr = %q", result.status, result.stderr)
	}
	if result.stdout != "hello" {
		t.Errorf("stdout = %q, want hello with no notice mixed in", result.stdout)
	}
	if !strings.Contains(result.stderr, "truncated") {
		t.Errorf("stderr = %q, want a truncation notice", result.stderr)
	}
}

// TestRunWritesOneLinePerListEntry proves the list format is stable.
func TestRunWritesOneLinePerListEntry(t *testing.T) {
	arguments := []string{
		"--client-credential", testClientCredential().String(),
		"--node-credential", testNodeCredential().String(),
		"--node-id", testNodeID(t),
		"--scope", "project",
		"--path", "",
		"file.list",
	}

	result := runCLI(t, http.StatusOK, listEnvelope, arguments, nil)

	if result.status != 0 {
		t.Fatalf("status = %d, stderr = %q", result.status, result.stderr)
	}
	want := "a.txt\tfile\t5\nb\tdir\t0\n"
	if result.stdout != want {
		t.Errorf("stdout = %q, want %q", result.stdout, want)
	}
}

// TestRunWritesStatFields proves the stat format reports every documented field,
// including the timestamp under its documented name.
func TestRunWritesStatFields(t *testing.T) {
	arguments := []string{
		"--client-credential", testClientCredential().String(),
		"--node-credential", testNodeCredential().String(),
		"--node-id", testNodeID(t),
		"--scope", "project",
		"--path", "a.txt",
		"file.stat",
	}

	result := runCLI(t, http.StatusOK, statEnvelope, arguments, nil)

	if result.status != 0 {
		t.Fatalf("status = %d, stderr = %q", result.status, result.stderr)
	}
	for _, want := range []string{
		"name\ta.txt",
		"type\tfile",
		"size\t5",
		"mode\t-rw-r--r--",
		"modified_at\t1700000000000",
		"is_symlink\tfalse",
	} {
		if !strings.Contains(result.stdout, want) {
			t.Errorf("stdout = %q, want it to contain %q", result.stdout, want)
		}
	}
}

// TestRunReportsASymlinkWithoutFollowingIt proves the stat output describes the link
// itself, which is the whole point of using Lstat.
func TestRunReportsASymlinkWithoutFollowingIt(t *testing.T) {
	arguments := []string{
		"--client-credential", testClientCredential().String(),
		"--node-credential", testNodeCredential().String(),
		"--node-id", testNodeID(t),
		"--scope", "project",
		"--path", "link",
		"file.stat",
	}

	result := runCLI(t, http.StatusOK, statSymlinkEnvelope, arguments, nil)

	if result.status != 0 {
		t.Fatalf("status = %d, stderr = %q", result.status, result.stderr)
	}
	if !strings.Contains(result.stdout, "is_symlink\ttrue") {
		t.Errorf("stdout = %q, want is_symlink true", result.stdout)
	}
	if !strings.Contains(result.stdout, "link_target\ta.txt") {
		t.Errorf("stdout = %q, want the link target", result.stdout)
	}
}

// TestRunExitsNonZeroOnARefusal proves a refusal puts the code and message on stderr
// and writes nothing to stdout, so a pipeline cannot consume a result that does not
// exist.
func TestRunExitsNonZeroOnARefusal(t *testing.T) {
	result := runCLI(t, http.StatusForbidden, refusalEnvelope, validArguments(t), nil)

	if result.status == 0 {
		t.Error("status = 0, want non-zero")
	}
	if result.stdout != "" {
		t.Errorf("stdout = %q, want empty", result.stdout)
	}
	if !strings.Contains(result.stderr, "denied") {
		t.Errorf("stderr = %q, want the code name", result.stderr)
	}
}

// TestRunWrapsTheEnvelopeWithJSON proves --json prints the whole envelope so a script
// can read the code and the request id.
func TestRunWrapsTheEnvelopeWithJSON(t *testing.T) {
	// The flag must precede the positional operation: Go's flag parser stops at the
	// first non-flag argument, so a flag after it would be read as a second positional
	// argument and refused.
	arguments := []string{
		"--client-credential", testClientCredential().String(),
		"--node-credential", testNodeCredential().String(),
		"--node-id", testNodeID(t),
		"--scope", "project",
		"--path", "a.txt",
		"--json",
		"file.read",
	}

	result := runCLI(t, http.StatusOK, readEnvelope, arguments, nil)

	if result.status != 0 {
		t.Fatalf("status = %d, stderr = %q", result.status, result.stderr)
	}

	var envelope Envelope
	if err := json.Unmarshal([]byte(result.stdout), &envelope); err != nil {
		t.Fatalf("stdout is not an envelope: %v (%q)", err, result.stdout)
	}
	if !envelope.Succeeded() {
		t.Error("envelope reported a failure")
	}
	if envelope.RequestID != "req_1" {
		t.Errorf("request_id = %q, want req_1", envelope.RequestID)
	}
}

// TestRunReportsAMalformedPayload proves a success envelope carrying an unreadable
// payload is an error rather than a silent empty result.
func TestRunReportsAMalformedPayload(t *testing.T) {
	malformed := `{"code":0,"message":"success","data":{"content":"not base64!"},"request_id":"req_1","timestamp":1700000000000}`

	result := runCLI(t, http.StatusOK, malformed, validArguments(t), nil)

	if result.status == 0 {
		t.Error("status = 0, want non-zero")
	}
	if result.stdout != "" {
		t.Errorf("stdout = %q, want empty", result.stdout)
	}
}

// TestRunReportsATransportFailure proves an unreachable Server exits non-zero.
func TestRunReportsATransportFailure(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(http.ResponseWriter, *http.Request) {}))
	url := server.URL
	server.Close()

	var stdout, stderr bytes.Buffer
	status := Run(validArguments(t), environment(map[string]string{EnvServerURL: url}), &stdout, &stderr)

	if status == 0 {
		t.Error("status = 0, want non-zero")
	}
	if stdout.String() != "" {
		t.Errorf("stdout = %q, want empty", stdout.String())
	}
}

// TestRunRefusesANilLookup proves a nil lookup is treated as an empty environment
// instead of panicking.
func TestRunRefusesANilLookup(t *testing.T) {
	var stdout, stderr bytes.Buffer
	status := Run(validArguments(t), nil, &stdout, &stderr)

	if status == 0 {
		t.Error("status = 0, want non-zero")
	}
}

// TestRedactNeverPrintsTheValue proves a redaction carries no prefix, no length and no
// other derived value.
func TestRedactNeverPrintsTheValue(t *testing.T) {
	secret := security.Secret("client-secret-0123456789abcdefghij")

	got := Redact(secret)
	if got == "" {
		t.Error("Redact returned an empty string for a non-empty secret")
	}
	if strings.Contains(got, "client") {
		t.Errorf("Redact = %q, want no part of the value", got)
	}
	if strings.Contains(got, "0123456789") {
		t.Errorf("Redact = %q, want no part of the value", got)
	}
	if Redact("") != "" {
		t.Errorf("Redact of an empty secret = %q, want empty", Redact(""))
	}
}

// TestDescribeRedactsBothSecretsAndPrintsThePublicValues proves a verbose dump is safe
// to paste into a bug report: the node id and both key identifiers are visible because
// they are public, and neither secret is.
func TestDescribeRedactsBothSecretsAndPrintsThePublicValues(t *testing.T) {
	nodeID := testNodeID(t)
	options := Options{
		ServerURL:        "https://example.com",
		ClientCredential: testClientCredential(),
		NodeCredential:   testNodeCredential(),
		NodeID:           nodeID,
		Operation:        protocol.OperationFileRead,
		Scope:            security.Scope("project"),
		Path:             "a.txt",
		Offset:           10,
		Length:           20,
	}

	got := Describe(options)

	if !strings.Contains(got, nodeID) {
		t.Errorf("Describe = %q, want the node id in full", got)
	}
	if !strings.Contains(got, options.ClientCredential.KeyID) {
		t.Errorf("Describe = %q, want the client key id in full", got)
	}
	if !strings.Contains(got, options.NodeCredential.KeyID) {
		t.Errorf("Describe = %q, want the node key id in full", got)
	}
	if strings.Contains(got, string(options.ClientCredential.Secret)) {
		t.Errorf("Describe = %q, want the client secret redacted", got)
	}
	if strings.Contains(got, string(options.NodeCredential.Secret)) {
		t.Errorf("Describe = %q, want the node secret redacted", got)
	}
	if !strings.Contains(got, "offset=10") {
		t.Errorf("Describe = %q, want the offset", got)
	}
	if !strings.Contains(got, "length=20") {
		t.Errorf("Describe = %q, want the length", got)
	}
}

// TestParseArgumentsDefaults proves the zero values are what an operator gets when a
// flag is omitted.
func TestParseArgumentsDefaults(t *testing.T) {
	options, jsonOutput, err := parseArguments([]string{
		"--server", "https://example.com",
		"--client-credential", testClientCredential().String(),
		"--node-credential", testNodeCredential().String(),
		"--node-id", testNodeID(t),
		"--scope", "project",
		"file.read",
	}, environment(nil))
	if err != nil {
		t.Fatalf("parseArguments: %v", err)
	}

	if jsonOutput {
		t.Error("jsonOutput = true, want false by default")
	}
	if options.Path != "" {
		t.Errorf("path = %q, want empty", options.Path)
	}
	if options.Offset != 0 || options.Length != 0 {
		t.Errorf("offset = %d, length = %d, want both zero", options.Offset, options.Length)
	}
	if options.RequestID != "" {
		t.Errorf("request id = %q, want empty", options.RequestID)
	}
}

// TestParseRefusalsExitTwo proves the invariant that ties the message prefix to the
// exit status for the refusals the argument parser produces: a message beginning
// `usage:` means the command line was rejected and nothing was sent, so the status is 2.
//
// The invariant is asserted over every parse-time refusal rather than only the one that
// was wrong, because a per-case assertion is what missed the `-o` defect: that test
// checked the message and the status separately and each was individually plausible.
// Only the pair was inconsistent, and only a test that reads the pair can see it.
//
// The scope is deliberately the parser. `Client.Send` also wraps its own local
// validation in ErrUsage, and `Run` returns 1 for those, so the same inconsistency
// exists on that path. That is a separate defect with a separate fix, recorded in
// `issues/issue-send-time-validation-exits-one-with-a-usage-message.md`; asserting the
// invariant over it here would make this test fail for a reason it does not own.
func TestParseRefusalsExitTwo(t *testing.T) {
	clientCredential := testClientCredential().String()
	nodeCredential := testNodeCredential().String()
	nodeID := testNodeID(t)

	directory := t.TempDir()
	existing := filepath.Join(directory, "out.bin")
	if err := os.WriteFile(existing, []byte("original"), 0o600); err != nil {
		t.Fatalf("seed the destination: %v", err)
	}

	cases := map[string][]string{
		"no operation":                {"--client-credential", clientCredential, "--node-credential", nodeCredential, "--node-id", nodeID, "--scope", "project"},
		"no client credential":        {"--node-credential", nodeCredential, "--node-id", nodeID, "--scope", "project", "file.read"},
		"no node credential":          {"--client-credential", clientCredential, "--node-id", nodeID, "--scope", "project", "file.read"},
		"no node id":                  {"--client-credential", clientCredential, "--node-credential", nodeCredential, "--scope", "project", "file.read"},
		"no scope":                    {"--client-credential", clientCredential, "--node-credential", nodeCredential, "--node-id", nodeID, "file.read"},
		"two operations":              {"--client-credential", clientCredential, "--node-credential", nodeCredential, "--node-id", nodeID, "--scope", "project", "file.read", "file.list"},
		"unknown operation":           {"--client-credential", clientCredential, "--node-credential", nodeCredential, "--node-id", nodeID, "--scope", "project", "file.delete"},
		"negative offset":             {"--client-credential", clientCredential, "--node-credential", nodeCredential, "--node-id", nodeID, "--scope", "project", "--offset", "-1", "file.read"},
		"negative length":             {"--client-credential", clientCredential, "--node-credential", nodeCredential, "--node-id", nodeID, "--scope", "project", "--length", "-1", "file.read"},
		"unknown flag":                {"--client-credential", clientCredential, "--node-credential", nodeCredential, "--node-id", nodeID, "--scope", "project", "--nope", "file.read"},
		"malformed client credential": {"--client-credential", "no-dot", "--node-credential", nodeCredential, "--node-id", nodeID, "--scope", "project", "file.read"},
		"malformed node credential":   {"--client-credential", clientCredential, "--node-credential", "no-dot", "--node-id", nodeID, "--scope", "project", "file.read"},
		"empty destination":           {"--client-credential", clientCredential, "--node-credential", nodeCredential, "--node-id", nodeID, "--scope", "project", "-o", "", "file.read"},
		"force without destination":   {"--client-credential", clientCredential, "--node-credential", nodeCredential, "--node-id", nodeID, "--scope", "project", "--force", "file.read"},
		"json with destination":       {"--client-credential", clientCredential, "--node-credential", nodeCredential, "--node-id", nodeID, "--scope", "project", "--json", "-o", existing, "file.read"},
	}

	for name, arguments := range cases {
		t.Run(name, func(t *testing.T) {
			result := runCLI(t, http.StatusOK, readEnvelope, arguments, nil)

			if !strings.HasPrefix(result.stderr, "connector-server cli: usage:") {
				t.Errorf("stderr = %q, want a usage: prefix", result.stderr)
			}
			if result.status != 2 {
				t.Errorf("status = %d, want 2 because the command line was rejected; stderr = %q", result.status, result.stderr)
			}
			if result.stdout != "" {
				t.Errorf("stdout = %q, want empty", result.stdout)
			}
		})
	}
}
