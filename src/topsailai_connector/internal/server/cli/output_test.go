package cli

import (
	"bytes"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"

	"topsailai_connector/internal/protocol"
)

// chunkServer answers `file.read` from an in-memory file, honouring offset and length
// the way the Node does, including the cap and the truncation flag.
//
// It reproduces the Node's own rule, including the known defect where a file whose
// size is exactly the cap reports truncated=true. Reproducing the defect is deliberate:
// the loop must be correct against the Node that exists, not against an ideal one.
type chunkServer struct {
	content []byte
	// requests counts the requests received, so a test can assert the loop made the
	// number of calls it claims.
	requests int
	// failAfter makes the server answer with a refusal after that many successful
	// responses. A negative value never fails.
	failAfter int
	mu        sync.Mutex
}

// capBytes mirrors the Node's response cap.
const capBytes = 256 * 1024

func (s *chunkServer) handler(t *testing.T) http.HandlerFunc {
	t.Helper()
	return func(writer http.ResponseWriter, request *http.Request) {
		s.mu.Lock()
		s.requests++
		count := s.requests
		s.mu.Unlock()

		if s.failAfter >= 0 && count > s.failAfter {
			writer.Header().Set("Content-Type", "application/json")
			_, _ = writer.Write([]byte(`{"code":1009,"message":"internal","data":null,"request_id":"req_x","timestamp":1}`))
			return
		}

		var body struct {
			Offset int64 `json:"offset"`
			Length int64 `json:"length"`
		}
		if err := json.NewDecoder(request.Body).Decode(&body); err != nil {
			t.Errorf("decode request body: %v", err)
		}

		limit := int64(capBytes)
		if body.Length > 0 && body.Length < limit {
			limit = body.Length
		}
		start := body.Offset
		if start > int64(len(s.content)) {
			start = int64(len(s.content))
		}
		end := start + limit
		if end > int64(len(s.content)) {
			end = int64(len(s.content))
		}
		chunk := s.content[start:end]
		truncated := int64(len(chunk)) == limit && limit == capBytes

		payload, err := json.Marshal(map[string]any{
			"content":   chunk,
			"size":      len(chunk),
			"truncated": truncated,
		})
		if err != nil {
			t.Errorf("encode payload: %v", err)
			return
		}
		envelope, err := json.Marshal(map[string]any{
			"code":       0,
			"message":    "success",
			"data":       json.RawMessage(payload),
			"request_id": "req_1",
			"timestamp":  1,
		})
		if err != nil {
			t.Errorf("encode envelope: %v", err)
			return
		}
		writer.Header().Set("Content-Type", "application/json")
		_, _ = writer.Write(envelope)
	}
}

// newChunkServer starts a server that serves content and returns it with its URL.
func newChunkServer(t *testing.T, content []byte, failAfter int) (*chunkServer, string) {
	t.Helper()
	state := &chunkServer{content: content, failAfter: failAfter}
	server := httptest.NewServer(state.handler(t))
	t.Cleanup(server.Close)
	return state, server.URL
}

// outputArguments builds arguments for a read with a destination.
func outputArguments(t *testing.T, destination string, extra ...string) []string {
	t.Helper()
	arguments := []string{
		"--client-credential", testClientCredential().String(),
		"--node-credential", testNodeCredential().String(),
		"--node-id", testNodeID(t),
		"--scope", "project",
		"--path", "a.bin",
	}
	arguments = append(arguments, extra...)
	arguments = append(arguments, "-o", destination, "file.read")
	return arguments
}

// runAgainst executes one invocation against a server URL.
func runAgainst(t *testing.T, serverURL string, arguments []string) runFixture {
	t.Helper()
	var stdout, stderr bytes.Buffer
	status := Run(arguments, environment(map[string]string{EnvServerURL: serverURL}), &stdout, &stderr)
	return runFixture{status: status, stdout: stdout.String(), stderr: stderr.String()}
}

// TestOutputWritesAWholeFileToStdout proves `-o -` fetches every chunk and writes the
// bytes unchanged, including bytes that are not valid UTF-8.
func TestOutputWritesAWholeFileToStdout(t *testing.T) {
	content := make([]byte, 3*capBytes+1234)
	for index := range content {
		content[index] = byte(index % 251)
	}
	state, url := newChunkServer(t, content, -1)

	fixture := runAgainst(t, url, outputArguments(t, "-"))

	if fixture.status != 0 {
		t.Fatalf("status = %d, want 0; stderr = %q", fixture.status, fixture.stderr)
	}
	if !bytes.Equal([]byte(fixture.stdout), content) {
		t.Errorf("stdout is %d bytes and does not match the %d byte source", len(fixture.stdout), len(content))
	}
	if state.requests != 4 {
		t.Errorf("requests = %d, want 4 for a file of %d bytes", state.requests, len(content))
	}
}

// TestOutputWritesAWholeFileToAPath proves the destination file holds the complete
// content and that the temporary file is gone afterwards.
func TestOutputWritesAWholeFileToAPath(t *testing.T) {
	content := make([]byte, 2*capBytes+7)
	for index := range content {
		content[index] = byte(index % 253)
	}
	_, url := newChunkServer(t, content, -1)

	directory := t.TempDir()
	destination := filepath.Join(directory, "out.bin")

	fixture := runAgainst(t, url, outputArguments(t, destination))

	if fixture.status != 0 {
		t.Fatalf("status = %d, want 0; stderr = %q", fixture.status, fixture.stderr)
	}
	written, err := os.ReadFile(destination)
	if err != nil {
		t.Fatalf("read the destination: %v", err)
	}
	if !bytes.Equal(written, content) {
		t.Errorf("destination is %d bytes and does not match the %d byte source", len(written), len(content))
	}
	if !strings.Contains(fixture.stderr, fmt.Sprintf("wrote %d bytes", len(content))) {
		t.Errorf("stderr = %q, want the byte count", fixture.stderr)
	}

	entries, err := os.ReadDir(directory)
	if err != nil {
		t.Fatalf("read the directory: %v", err)
	}
	if len(entries) != 1 || entries[0].Name() != "out.bin" {
		names := make([]string, 0, len(entries))
		for _, entry := range entries {
			names = append(names, entry.Name())
		}
		t.Errorf("directory holds %v, want only out.bin", names)
	}
}

// TestOutputHandlesTheEmptyFile proves an empty file terminates on the first response
// instead of looping forever.
func TestOutputHandlesTheEmptyFile(t *testing.T) {
	state, url := newChunkServer(t, nil, -1)

	fixture := runAgainst(t, url, outputArguments(t, "-"))

	if fixture.status != 0 {
		t.Fatalf("status = %d, want 0; stderr = %q", fixture.status, fixture.stderr)
	}
	if fixture.stdout != "" {
		t.Errorf("stdout = %q, want empty", fixture.stdout)
	}
	if state.requests != 1 {
		t.Errorf("requests = %d, want 1", state.requests)
	}
}

// TestOutputHandlesAFileOfExactlyTheCap proves the loop stops on a file whose size is
// exactly the cap, even though the Node reports truncated=true for it.
//
// This is the case the known defect produces. The loop must not depend on the flag
// being correct, so it stops on the zero-size response that follows instead of
// looping or dropping data.
func TestOutputHandlesAFileOfExactlyTheCap(t *testing.T) {
	content := make([]byte, capBytes)
	for index := range content {
		content[index] = byte(index % 249)
	}
	state, url := newChunkServer(t, content, -1)

	fixture := runAgainst(t, url, outputArguments(t, "-"))

	if fixture.status != 0 {
		t.Fatalf("status = %d, want 0; stderr = %q", fixture.status, fixture.stderr)
	}
	if !bytes.Equal([]byte(fixture.stdout), content) {
		t.Errorf("stdout is %d bytes, want %d", len(fixture.stdout), len(content))
	}
	// One request returns the whole file with truncated=true, so a second request is
	// needed to learn that nothing remains. Two requests is the cost of not trusting
	// the flag; more than two would mean the loop is not terminating on size.
	if state.requests != 2 {
		t.Errorf("requests = %d, want 2", state.requests)
	}
}

// TestOutputHandlesOneByteOverTheCap proves the boundary above the cap is read whole.
func TestOutputHandlesOneByteOverTheCap(t *testing.T) {
	content := make([]byte, capBytes+1)
	for index := range content {
		content[index] = byte(index % 247)
	}
	state, url := newChunkServer(t, content, -1)

	fixture := runAgainst(t, url, outputArguments(t, "-"))

	if fixture.status != 0 {
		t.Fatalf("status = %d, want 0; stderr = %q", fixture.status, fixture.stderr)
	}
	if !bytes.Equal([]byte(fixture.stdout), content) {
		t.Errorf("stdout is %d bytes, want %d", len(fixture.stdout), len(content))
	}
	if state.requests != 2 {
		t.Errorf("requests = %d, want 2", state.requests)
	}
}

// TestOutputHonoursOffsetAndLength proves a requested range is fetched and nothing
// beyond it is written.
func TestOutputHonoursOffsetAndLength(t *testing.T) {
	content := make([]byte, 4*capBytes)
	for index := range content {
		content[index] = byte(index % 241)
	}
	_, url := newChunkServer(t, content, -1)

	start := int64(capBytes + 100)
	want := content[start : start+capBytes+50]

	fixture := runAgainst(t, url, outputArguments(t, "-", "--offset", fmt.Sprint(start), "--length", fmt.Sprint(len(want))))

	if fixture.status != 0 {
		t.Fatalf("status = %d, want 0; stderr = %q", fixture.status, fixture.stderr)
	}
	if !bytes.Equal([]byte(fixture.stdout), want) {
		t.Errorf("stdout is %d bytes, want the %d byte range", len(fixture.stdout), len(want))
	}
}

// TestOutputRefusesAnExistingDestination proves a read does not silently replace a
// local file.
func TestOutputRefusesAnExistingDestination(t *testing.T) {
	_, url := newChunkServer(t, []byte("new content"), -1)

	directory := t.TempDir()
	destination := filepath.Join(directory, "out.bin")
	if err := os.WriteFile(destination, []byte("original"), 0o600); err != nil {
		t.Fatalf("seed the destination: %v", err)
	}

	fixture := runAgainst(t, url, outputArguments(t, destination))

	if fixture.status == 0 {
		t.Fatal("status = 0, want a refusal")
	}
	if !strings.Contains(fixture.stderr, "--force") {
		t.Errorf("stderr = %q, want a hint about --force", fixture.stderr)
	}
	kept, err := os.ReadFile(destination)
	if err != nil {
		t.Fatalf("read the destination: %v", err)
	}
	if string(kept) != "original" {
		t.Errorf("destination = %q, want the original content untouched", kept)
	}
}

// TestOutputForceReplacesAnExistingDestination proves --force is the only way to
// replace a file, and that it does replace it.
func TestOutputForceReplacesAnExistingDestination(t *testing.T) {
	content := []byte("replacement content")
	_, url := newChunkServer(t, content, -1)

	directory := t.TempDir()
	destination := filepath.Join(directory, "out.bin")
	if err := os.WriteFile(destination, []byte("original"), 0o600); err != nil {
		t.Fatalf("seed the destination: %v", err)
	}

	fixture := runAgainst(t, url, outputArguments(t, destination, "--force"))

	if fixture.status != 0 {
		t.Fatalf("status = %d, want 0; stderr = %q", fixture.status, fixture.stderr)
	}
	written, err := os.ReadFile(destination)
	if err != nil {
		t.Fatalf("read the destination: %v", err)
	}
	if !bytes.Equal(written, content) {
		t.Errorf("destination = %q, want %q", written, content)
	}
}

// TestOutputLeavesNoPartialFileOnFailure proves a failure mid-read leaves the
// destination absent and no temporary file behind.
//
// This is the property that makes "the file exists" mean "the file is complete".
func TestOutputLeavesNoPartialFileOnFailure(t *testing.T) {
	content := make([]byte, 3*capBytes)
	_, url := newChunkServer(t, content, 1)

	directory := t.TempDir()
	destination := filepath.Join(directory, "out.bin")

	fixture := runAgainst(t, url, outputArguments(t, destination))

	if fixture.status == 0 {
		t.Fatal("status = 0, want a failure")
	}
	if _, err := os.Stat(destination); !os.IsNotExist(err) {
		t.Errorf("destination exists after a failed read; err = %v", err)
	}
	entries, err := os.ReadDir(directory)
	if err != nil {
		t.Fatalf("read the directory: %v", err)
	}
	if len(entries) != 0 {
		names := make([]string, 0, len(entries))
		for _, entry := range entries {
			names = append(names, entry.Name())
		}
		t.Errorf("directory holds %v after a failed read, want nothing", names)
	}
}

// TestOutputRefusesJsonCombinedWithADestination proves the two output contracts cannot
// both be requested.
func TestOutputRefusesJsonCombinedWithADestination(t *testing.T) {
	_, url := newChunkServer(t, []byte("x"), -1)

	fixture := runAgainst(t, url, outputArguments(t, "-", "--json"))

	if fixture.status == 0 {
		t.Fatal("status = 0, want a refusal")
	}
	if !strings.Contains(fixture.stderr, "--json") {
		t.Errorf("stderr = %q, want a message naming --json", fixture.stderr)
	}
}

// TestOutputRefusesForceWithoutADestination proves --force alone is refused, so a
// caller cannot believe a protection was in effect when no file was written.
func TestOutputRefusesForceWithoutADestination(t *testing.T) {
	_, url := newChunkServer(t, []byte("x"), -1)

	arguments := []string{
		"--client-credential", testClientCredential().String(),
		"--node-credential", testNodeCredential().String(),
		"--node-id", testNodeID(t),
		"--scope", "project",
		"--path", "a.bin",
		"--force",
		"file.read",
	}
	fixture := runAgainst(t, url, arguments)

	if fixture.status == 0 {
		t.Fatal("status = 0, want a refusal")
	}
	if !strings.Contains(fixture.stderr, "--force") {
		t.Errorf("stderr = %q, want a message naming --force", fixture.stderr)
	}
}

// TestOutputAppliesToListAndStat proves -o is not read-only, so a caller does not have
// to remember which operation accepts it.
func TestOutputAppliesToListAndStat(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
		writer.Header().Set("Content-Type", "application/json")
		_, _ = writer.Write([]byte(listEnvelope))
	}))
	t.Cleanup(server.Close)

	directory := t.TempDir()
	destination := filepath.Join(directory, "listing.txt")

	arguments := []string{
		"--client-credential", testClientCredential().String(),
		"--node-credential", testNodeCredential().String(),
		"--node-id", testNodeID(t),
		"--scope", "project",
		"-o", destination,
		"file.list",
	}
	fixture := runAgainst(t, server.URL, arguments)

	if fixture.status != 0 {
		t.Fatalf("status = %d, want 0; stderr = %q", fixture.status, fixture.stderr)
	}
	written, err := os.ReadFile(destination)
	if err != nil {
		t.Fatalf("read the destination: %v", err)
	}
	if !strings.Contains(string(written), "a.txt") {
		t.Errorf("destination = %q, want the listing", written)
	}
}

// TestOutputWithoutTheFlagKeepsOneRequest proves the historical behaviour is unchanged:
// no -o means one request and a truncation notice on stderr.
func TestOutputWithoutTheFlagKeepsOneRequest(t *testing.T) {
	content := make([]byte, 2*capBytes)
	state, url := newChunkServer(t, content, -1)

	arguments := []string{
		"--client-credential", testClientCredential().String(),
		"--node-credential", testNodeCredential().String(),
		"--node-id", testNodeID(t),
		"--scope", "project",
		"--path", "a.bin",
		"file.read",
	}
	fixture := runAgainst(t, url, arguments)

	if fixture.status != 0 {
		t.Fatalf("status = %d, want 0; stderr = %q", fixture.status, fixture.stderr)
	}
	if state.requests != 1 {
		t.Errorf("requests = %d, want 1 without -o", state.requests)
	}
	if len(fixture.stdout) != capBytes {
		t.Errorf("stdout is %d bytes, want one chunk of %d", len(fixture.stdout), capBytes)
	}
	if !strings.Contains(fixture.stderr, "truncated") {
		t.Errorf("stderr = %q, want the truncation notice", fixture.stderr)
	}
}

// TestOutputDecodesBase64Content proves the payload is decoded from base64 rather than
// written as the encoded text.
func TestOutputDecodesBase64Content(t *testing.T) {
	raw := []byte{0x00, 0xff, 0x80, 0x7f}
	encoded := base64.StdEncoding.EncodeToString(raw)
	envelope := fmt.Sprintf(`{"code":0,"message":"success","data":{"content":%q,"size":4,"truncated":false},"request_id":"req_1","timestamp":1}`, encoded)

	server := httptest.NewServer(http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
		writer.Header().Set("Content-Type", "application/json")
		_, _ = writer.Write([]byte(envelope))
	}))
	t.Cleanup(server.Close)

	fixture := runAgainst(t, server.URL, outputArguments(t, "-"))

	if fixture.status != 0 {
		t.Fatalf("status = %d, want 0; stderr = %q", fixture.status, fixture.stderr)
	}
	if !bytes.Equal([]byte(fixture.stdout), raw) {
		t.Errorf("stdout = %v, want %v", []byte(fixture.stdout), raw)
	}
}

// TestOutputRefusesAnUnwritableDirectory proves a destination in a missing directory is
// reported rather than silently ignored.
func TestOutputRefusesAnUnwritableDirectory(t *testing.T) {
	_, url := newChunkServer(t, []byte("x"), -1)

	destination := filepath.Join(t.TempDir(), "missing", "out.bin")
	fixture := runAgainst(t, url, outputArguments(t, destination))

	if fixture.status == 0 {
		t.Fatal("status = 0, want a failure")
	}
	if !strings.Contains(fixture.stderr, "temporary file") {
		t.Errorf("stderr = %q, want a message about the temporary file", fixture.stderr)
	}
}

// TestOutputOperationIsStillRead proves the loop sends file.read and not another
// operation, so a destination cannot change what is asked for.
func TestOutputOperationIsStillRead(t *testing.T) {
	var seen []string
	server := httptest.NewServer(http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
		var body struct {
			Operation string `json:"operation"`
		}
		_ = json.NewDecoder(request.Body).Decode(&body)
		seen = append(seen, body.Operation)
		writer.Header().Set("Content-Type", "application/json")
		_, _ = writer.Write([]byte(`{"code":0,"message":"success","data":{"content":"","size":0,"truncated":false},"request_id":"req_1","timestamp":1}`))
	}))
	t.Cleanup(server.Close)

	fixture := runAgainst(t, server.URL, outputArguments(t, "-"))

	if fixture.status != 0 {
		t.Fatalf("status = %d, want 0; stderr = %q", fixture.status, fixture.stderr)
	}
	if len(seen) == 0 {
		t.Fatal("no request was sent")
	}
	for _, operation := range seen {
		if operation != string(protocol.OperationFileRead) {
			t.Errorf("operation = %q, want file.read", operation)
		}
	}
}

// TestOutputStopsOnAContradictoryResponse proves the zero-size guard is what stops a
// response that claims more remains but delivered nothing.
//
// The Node does not produce that response today, so this test is the only evidence the
// guard is load-bearing. The server answers the contradiction once and then answers a
// normal end of file, so the loop terminates either way and the request count is the
// observable difference: one request with the guard, two without it. A test that let the
// loop spin would hang instead of failing, which is why the second response exists.
func TestOutputStopsOnAContradictoryResponse(t *testing.T) {
	var mu sync.Mutex
	requests := 0
	server := httptest.NewServer(http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
		mu.Lock()
		requests++
		count := requests
		mu.Unlock()

		writer.Header().Set("Content-Type", "application/json")
		if count == 1 {
			// Claims more remains, delivers nothing, and reports no progress.
			_, _ = writer.Write([]byte(`{"code":0,"message":"success","data":{"content":"","size":0,"truncated":true},"request_id":"req_1","timestamp":1}`))
			return
		}
		_, _ = writer.Write([]byte(`{"code":0,"message":"success","data":{"content":"","size":0,"truncated":false},"request_id":"req_2","timestamp":1}`))
	}))
	t.Cleanup(server.Close)

	fixture := runAgainst(t, server.URL, outputArguments(t, "-"))

	if fixture.status != 0 {
		t.Fatalf("status = %d, want 0; stderr = %q", fixture.status, fixture.stderr)
	}
	mu.Lock()
	seen := requests
	mu.Unlock()
	if seen != 1 {
		t.Errorf("requests = %d, want 1: a zero-size response must stop the loop", seen)
	}
	if fixture.stdout != "" {
		t.Errorf("stdout = %q, want nothing", fixture.stdout)
	}
}

// TestOutputRefusesAnEmptyDestination proves `-o ""` is refused rather than read as
// "no destination".
//
// The two are different requests: an omitted flag keeps the single-request behaviour,
// while an empty value asks for a destination and names none. Treating the second as
// the first would run one request while the caller believed a whole-file read was
// requested, which is the failure mode a default value cannot express.
func TestOutputRefusesAnEmptyDestination(t *testing.T) {
	_, url := newChunkServer(t, []byte("x"), -1)

	arguments := []string{
		"--client-credential", testClientCredential().String(),
		"--node-credential", testNodeCredential().String(),
		"--node-id", testNodeID(t),
		"--scope", "project",
		"--path", "a.bin",
		"-o", "",
		"file.read",
	}
	fixture := runAgainst(t, url, arguments)

	if fixture.status == 0 {
		t.Fatal("status = 0, want a failure for an empty destination")
	}
	if !strings.Contains(fixture.stderr, "needs a destination") {
		t.Errorf("stderr = %q, want a message about the destination", fixture.stderr)
	}
	if fixture.stdout != "" {
		t.Errorf("stdout = %q, want nothing", fixture.stdout)
	}
}
