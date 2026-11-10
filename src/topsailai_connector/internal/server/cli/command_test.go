package cli

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
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
		"--client-token", string(testClientToken()),
		"--node", testIdentity(t).String(),
		"--scope", "project",
		"--path", "a.txt",
		"file.read",
	}
}

// TestRunRefusesMissingConfiguration proves every required value is reported as a
// usage error with a non-zero status.
func TestRunRefusesMissingConfiguration(t *testing.T) {
	identity := testIdentity(t)
	clientToken := string(testClientToken())

	cases := map[string][]string{
		"no operation":      {"--client-token", clientToken, "--node", identity.String(), "--scope", "project"},
		"no client token":   {"--node", identity.String(), "--scope", "project", "file.read"},
		"no node pair":      {"--client-token", clientToken, "--scope", "project", "file.read"},
		"no scope":          {"--client-token", clientToken, "--node", identity.String(), "file.read"},
		"two operations":    {"--client-token", clientToken, "--node", identity.String(), "--scope", "project", "file.read", "file.list"},
		"unknown operation": {"--client-token", clientToken, "--node", identity.String(), "--scope", "project", "file.delete"},
		"negative offset":   {"--client-token", clientToken, "--node", identity.String(), "--scope", "project", "--offset", "-1", "file.read"},
		"negative length":   {"--client-token", clientToken, "--node", identity.String(), "--scope", "project", "--length", "-1", "file.read"},
		"unknown flag":      {"--client-token", clientToken, "--node", identity.String(), "--scope", "project", "--nope", "file.read"},
	}

	for name, arguments := range cases {
		t.Run(name, func(t *testing.T) {
			result := runCLI(t, http.StatusOK, readEnvelope, arguments, nil)

			if result.status == 0 {
				t.Error("status = 0, want non-zero")
			}
			if result.stdout != "" {
				t.Errorf("stdout = %q, want empty", result.stdout)
			}
			if result.stderr == "" {
				t.Error("stderr is empty, want a usage message")
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

// TestRunReadsTheEnvironment proves the documented variables are honoured, so a
// script can export them instead of repeating flags.
func TestRunReadsTheEnvironment(t *testing.T) {
	identity := testIdentity(t)

	result := runCLI(t, http.StatusOK, readEnvelope, []string{"--scope", "project", "--path", "a.txt", "file.read"}, map[string]string{
		EnvClientToken: string(testClientToken()),
		EnvNode:        identity.String(),
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
	identity := testIdentity(t)

	// The environment carries a malformed pair; the flag carries a valid one. If the
	// environment won, the request would be refused locally.
	result := runCLI(t, http.StatusOK, readEnvelope, []string{
		"--node", identity.String(),
		"--scope", "project",
		"--path", "a.txt",
		"file.read",
	}, map[string]string{
		EnvClientToken: string(testClientToken()),
		EnvNode:        "malformed",
	})

	if result.status != 0 {
		t.Fatalf("status = %d, stderr = %q", result.status, result.stderr)
	}
}

// TestRunWritesRawBytesForRead proves a read payload is written as raw bytes so it
// can be piped.
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
		"--client-token", string(testClientToken()),
		"--node", testIdentity(t).String(),
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
		"--client-token", string(testClientToken()),
		"--node", testIdentity(t).String(),
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
		"--client-token", string(testClientToken()),
		"--node", testIdentity(t).String(),
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
	// first non-flag argument, so a flag after it would be read as a second
	// positional argument and refused.
	arguments := []string{
		"--client-token", string(testClientToken()),
		"--node", testIdentity(t).String(),
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

// TestRedactNeverPrintsTheValue proves a redaction carries no prefix, no length and
// no other derived value.
func TestRedactNeverPrintsTheValue(t *testing.T) {
	secret := security.Secret("client-token-0123456789")

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

// TestDescribeRedactsBothSecretsAndPrintsTheNodeID proves a verbose dump is safe to
// paste into a bug report: the node id is visible because it is not a secret, and
// neither secret is.
func TestDescribeRedactsBothSecretsAndPrintsTheNodeID(t *testing.T) {
	identity := testIdentity(t)
	options := Options{
		ServerURL:   "https://example.com",
		ClientToken: testClientToken(),
		Pair:        identity.String(),
		Operation:   protocol.OperationFileRead,
		Scope:       security.Scope("project"),
		Path:        "a.txt",
		Offset:      10,
		Length:      20,
	}

	got := Describe(options)

	if !strings.Contains(got, identity.ID) {
		t.Errorf("Describe = %q, want the node id in full", got)
	}
	if strings.Contains(got, string(identity.Token)) {
		t.Errorf("Describe = %q, want the node token redacted", got)
	}
	if strings.Contains(got, string(options.ClientToken)) {
		t.Errorf("Describe = %q, want the client token redacted", got)
	}
	if !strings.Contains(got, "offset=10") {
		t.Errorf("Describe = %q, want the offset", got)
	}
	if !strings.Contains(got, "length=20") {
		t.Errorf("Describe = %q, want the length", got)
	}
}

// TestDescribeReportsAMalformedPair proves a dump of a broken pair does not panic and
// does not print the value.
func TestDescribeReportsAMalformedPair(t *testing.T) {
	got := Describe(Options{Pair: "not-a-pair"})

	if !strings.Contains(got, "<malformed>") {
		t.Errorf("Describe = %q, want a malformed marker", got)
	}
	if strings.Contains(got, "not-a-pair") {
		t.Errorf("Describe = %q, want the value withheld", got)
	}
}

// TestParseArgumentsDefaults proves the zero values are what an operator gets when a
// flag is omitted.
func TestParseArgumentsDefaults(t *testing.T) {
	identity := testIdentity(t)

	options, jsonOutput, err := parseArguments([]string{
		"--server", "https://example.com",
		"--client-token", string(testClientToken()),
		"--node", identity.String(),
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
