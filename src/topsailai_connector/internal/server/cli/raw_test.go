package cli

import (
	"bytes"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"testing"
)

// rawServer answers `file.read` with the byte stream when the caller opted in, and
// with the documented envelope otherwise.
//
// It reproduces the Server's own rule rather than a convenient one: the raw shape is
// used only for a success that carries bytes, so a refusal and an empty file both
// arrive as the envelope. A test server that always answered raw would prove the CLI
// can read bytes, not that it can tell the three answers apart.
type rawServer struct {
	content []byte
	// requests counts the requests received, so a test can assert the loop made the
	// number of calls it claims.
	requests int
	// accepts records the Accept header of every request.
	accepts []string
	// refuse makes every answer a refusal envelope.
	refuse bool
	// omitTruncated drops the truncation header from a raw answer.
	omitTruncated bool
	// badTruncated sends a value that is not a boolean.
	badTruncated string
	// shortBody declares more bytes than it writes.
	shortBody bool
	// oversized writes more bytes than the CLI's limit.
	oversized bool
	// ignoreAccept reproduces a Server that predates the opt-in.
	ignoreAccept bool
	mu           sync.Mutex
}

func (s *rawServer) handler(t *testing.T) http.HandlerFunc {
	t.Helper()
	return func(writer http.ResponseWriter, request *http.Request) {
		s.mu.Lock()
		s.requests++
		s.accepts = append(s.accepts, request.Header.Get("Accept"))
		s.mu.Unlock()

		if s.refuse {
			writer.Header().Set("Content-Type", "application/json")
			writer.WriteHeader(http.StatusForbidden)
			_, _ = writer.Write([]byte(`{"code":1005,"message":"denied","data":null,"request_id":"req_5","timestamp":1}`))
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
		truncated := limit == capBytes && int64(len(chunk)) == limit && end < int64(len(s.content))

		wantsRaw := !s.ignoreAccept && strings.Contains(request.Header.Get("Accept"), rawContentMediaType)
		if wantsRaw && len(chunk) > 0 {
			writer.Header().Set("Content-Type", rawContentMediaType)
			if s.oversized {
				writer.Header().Set("Content-Length", "999999999")
				_, _ = writer.Write(bytes.Repeat([]byte("x"), int(MaxResponseBytes)+1))
				return
			}
			if s.shortBody {
				writer.Header().Set("Content-Length", "100")
				_, _ = writer.Write(chunk)
				return
			}
			writer.Header().Set("Content-Length", strconv.Itoa(len(chunk)))
			writer.Header().Set("X-Request-Id", "req_1")
			if s.badTruncated != "" {
				writer.Header().Set(truncatedHeader, s.badTruncated)
			} else if !s.omitTruncated {
				writer.Header().Set(truncatedHeader, boolText(truncated))
			}
			writer.WriteHeader(http.StatusOK)
			_, _ = writer.Write(chunk)
			return
		}

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

// boolText formats a boolean the way the Server does.
func boolText(value bool) string {
	return strconv.FormatBool(value)
}

// newRawServer starts a server and returns it with its URL.
func newRawServer(t *testing.T, content []byte) (*rawServer, string) {
	t.Helper()
	state := &rawServer{content: content}
	server := httptest.NewServer(state.handler(t))
	t.Cleanup(server.Close)
	return state, server.URL
}

// TestRawReadSendsTheAcceptHeader proves a whole-file read asks for the byte stream.
//
// Without the header the Server answers with the envelope, so the cheaper path exists
// and nothing uses it. That is the defect this test exists to prevent, and it is
// invisible in every other test because both shapes produce the same bytes.
func TestRawReadSendsTheAcceptHeader(t *testing.T) {
	content := []byte("hello, connector")
	state, url := newRawServer(t, content)

	destination := filepath.Join(t.TempDir(), "out.bin")
	fixture := runAgainst(t, url, outputArguments(t, destination))

	if fixture.status != 0 {
		t.Fatalf("status = %d, want 0; stderr = %q", fixture.status, fixture.stderr)
	}
	state.mu.Lock()
	accepts := append([]string(nil), state.accepts...)
	state.mu.Unlock()
	if len(accepts) == 0 {
		t.Fatal("no request was made")
	}
	for index, accept := range accepts {
		if !strings.Contains(accept, rawContentMediaType) {
			t.Errorf("request %d Accept = %q, want %q", index, accept, rawContentMediaType)
		}
	}

	written, err := os.ReadFile(destination)
	if err != nil {
		t.Fatalf("read the destination: %v", err)
	}
	if !bytes.Equal(written, content) {
		t.Errorf("destination = %q, want %q", written, content)
	}
}

// TestRawReadConsumesABodyThatIsNotJson proves the raw body is read as bytes.
//
// The body is deliberately not JSON. Before the change it was passed to the envelope
// decoder, which failed with `decode response`, so this test fails if the raw path is
// routed through that decoder again.
func TestRawReadConsumesABodyThatIsNotJson(t *testing.T) {
	content := []byte{0x00, 0xff, 0x80, 0x7f, 'n', 'o', 't', ' ', 'j', 's', 'o', 'n'}
	_, url := newRawServer(t, content)

	destination := filepath.Join(t.TempDir(), "out.bin")
	fixture := runAgainst(t, url, outputArguments(t, destination))

	if fixture.status != 0 {
		t.Fatalf("status = %d, want 0; stderr = %q", fixture.status, fixture.stderr)
	}
	written, err := os.ReadFile(destination)
	if err != nil {
		t.Fatalf("read the destination: %v", err)
	}
	if !bytes.Equal(written, content) {
		t.Errorf("destination = %v, want %v", written, content)
	}
}

// TestRawReadFollowsTheTruncationHeader proves the loop continues on a truncated raw
// answer and stops on a complete one.
//
// The flag has no JSON field to live in on this path, so a loop that read it from the
// body would stop after the first chunk and report success. That is silent truncation,
// which is the failure the flag exists to prevent.
func TestRawReadFollowsTheTruncationHeader(t *testing.T) {
	content := make([]byte, 2*capBytes)
	for index := range content {
		content[index] = byte(index % 251)
	}
	state, url := newRawServer(t, content)

	destination := filepath.Join(t.TempDir(), "out.bin")
	fixture := runAgainst(t, url, outputArguments(t, destination))

	if fixture.status != 0 {
		t.Fatalf("status = %d, want 0; stderr = %q", fixture.status, fixture.stderr)
	}
	if state.requests != 2 {
		t.Errorf("requests = %d, want 2: the first answer is truncated", state.requests)
	}
	written, err := os.ReadFile(destination)
	if err != nil {
		t.Fatalf("read the destination: %v", err)
	}
	if !bytes.Equal(written, content) {
		t.Errorf("destination is %d bytes, want %d", len(written), len(content))
	}
}

// TestRawReadRefusesAMissingTruncationHeader proves the flag is required.
//
// Treating a missing header as `false` would stop a whole-file read after one chunk
// and report success, so the refusal is the safe answer rather than a strictness.
func TestRawReadRefusesAMissingTruncationHeader(t *testing.T) {
	content := make([]byte, 2*capBytes)
	state, url := newRawServer(t, content)
	state.omitTruncated = true

	destination := filepath.Join(t.TempDir(), "out.bin")
	fixture := runAgainst(t, url, outputArguments(t, destination))

	if fixture.status == 0 {
		t.Fatalf("status = 0, want a refusal; stdout = %q", fixture.stdout)
	}
	if !strings.Contains(fixture.stderr, truncatedHeader) {
		t.Errorf("stderr = %q, want a message naming %s", fixture.stderr, truncatedHeader)
	}
	if _, err := os.Stat(destination); !os.IsNotExist(err) {
		t.Errorf("the destination exists after a refusal, want no file")
	}
}

// TestRawReadRefusesAnUnparsableTruncationHeader proves a value that is not a boolean
// is refused rather than guessed.
func TestRawReadRefusesAnUnparsableTruncationHeader(t *testing.T) {
	state, url := newRawServer(t, []byte("hello"))
	state.badTruncated = "yes"

	destination := filepath.Join(t.TempDir(), "out.bin")
	fixture := runAgainst(t, url, outputArguments(t, destination))

	if fixture.status == 0 {
		t.Fatalf("status = 0, want a refusal; stdout = %q", fixture.stdout)
	}
	if !strings.Contains(fixture.stderr, truncatedHeader) {
		t.Errorf("stderr = %q, want a message naming %s", fixture.stderr, truncatedHeader)
	}
}

// TestRawReadRefusesAShortBody proves a body shorter than its declared length is
// refused rather than published as a complete file.
//
// The refusal comes from the HTTP transport, which reports `unexpected EOF` before the
// explicit length check runs. That is why the assertion is on the refusal and not on a
// particular message: the transport is the layer that catches this case, and a test
// that demanded the explicit message would be asserting a layer that never runs.
//
// The explicit check is covered separately by TestReadRawResponseComparesTheDeclaredLength,
// which calls it directly, so neither layer is left untested.
func TestRawReadRefusesAShortBody(t *testing.T) {
	state, url := newRawServer(t, []byte("hello, connector"))
	state.shortBody = true

	destination := filepath.Join(t.TempDir(), "out.bin")
	fixture := runAgainst(t, url, outputArguments(t, destination))

	if fixture.status == 0 {
		t.Fatalf("status = 0, want a refusal; stdout = %q", fixture.stdout)
	}
	if _, err := os.Stat(destination); !os.IsNotExist(err) {
		t.Errorf("the destination exists after a refusal, want no file")
	}
}

// TestReadRawResponseComparesTheDeclaredLength proves the explicit length check works.
//
// It is called directly because the transport catches a short body first, so an
// end-to-end test cannot reach this code. Without this test the check would be
// unexercised, and a check nobody runs is a check that can be deleted without a
// failure.
func TestReadRawResponseComparesTheDeclaredLength(t *testing.T) {
	response := &http.Response{
		Header:        http.Header{truncatedHeader: []string{"false"}},
		Body:          io.NopCloser(strings.NewReader("short")),
		ContentLength: 100,
	}

	_, err := readRawResponse(response, MaxResponseBytes)
	if err == nil {
		t.Fatal("readRawResponse accepted a body shorter than its declared length")
	}
	if !strings.Contains(err.Error(), "declared") {
		t.Errorf("error = %q, want a message about the declared length", err)
	}
}

// TestRawReadRefusesAnOversizedBody proves the raw body is bounded by the same limit
// as the envelope path.
func TestRawReadRefusesAnOversizedBody(t *testing.T) {
	state, url := newRawServer(t, []byte("hello"))
	state.oversized = true

	destination := filepath.Join(t.TempDir(), "out.bin")
	fixture := runAgainst(t, url, outputArguments(t, destination))

	if fixture.status == 0 {
		t.Fatalf("status = 0, want a refusal; stdout = %q", fixture.stdout)
	}
	if !strings.Contains(fixture.stderr, "exceeds") {
		t.Errorf("stderr = %q, want a message about the limit", fixture.stderr)
	}
}

// TestRawReadReportsARefusalAsTheEnvelope proves a refusal keeps its code and message.
//
// The Server answers a refusal with the envelope even when the caller opted in, so the
// CLI must decode it rather than treat the JSON body as file content.
func TestRawReadReportsARefusalAsTheEnvelope(t *testing.T) {
	state, url := newRawServer(t, []byte("hello"))
	state.refuse = true

	destination := filepath.Join(t.TempDir(), "out.bin")
	fixture := runAgainst(t, url, outputArguments(t, destination))

	if fixture.status == 0 {
		t.Fatalf("status = 0, want a refusal")
	}
	if !strings.Contains(fixture.stderr, "denied") {
		t.Errorf("stderr = %q, want the code name", fixture.stderr)
	}
	if _, err := os.Stat(destination); !os.IsNotExist(err) {
		t.Errorf("the destination exists after a refusal, want no file")
	}
}

// TestRawReadHandlesAnEmptyFile proves a success with no bytes is not a refusal.
//
// The Server answers an empty file with the envelope, because there is nothing to
// stream. A CLI that read that as a refusal would report an error for a file that was
// read correctly.
func TestRawReadHandlesAnEmptyFile(t *testing.T) {
	_, url := newRawServer(t, nil)

	destination := filepath.Join(t.TempDir(), "out.bin")
	fixture := runAgainst(t, url, outputArguments(t, destination))

	if fixture.status != 0 {
		t.Fatalf("status = %d, want 0; stderr = %q", fixture.status, fixture.stderr)
	}
	written, err := os.ReadFile(destination)
	if err != nil {
		t.Fatalf("read the destination: %v", err)
	}
	if len(written) != 0 {
		t.Errorf("destination is %d bytes, want 0", len(written))
	}
}

// TestRawReadFallsBackToAnOlderServer proves a Server that ignores the opt-in still
// delivers the content.
//
// The envelope carries the bytes, so a CLI that discarded them would report a
// successful read of nothing. That is worse than a refusal, because the caller has no
// signal that anything went wrong.
func TestRawReadFallsBackToAnOlderServer(t *testing.T) {
	content := []byte("hello, connector")
	state, url := newRawServer(t, content)
	state.ignoreAccept = true

	destination := filepath.Join(t.TempDir(), "out.bin")
	fixture := runAgainst(t, url, outputArguments(t, destination))

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

// TestRawReadHonoursOffsetAndLength proves the range flags still select a range on the
// raw path.
func TestRawReadHonoursOffsetAndLength(t *testing.T) {
	content := []byte("0123456789abcdef")
	_, url := newRawServer(t, content)

	destination := filepath.Join(t.TempDir(), "out.bin")
	fixture := runAgainst(t, url, outputArguments(t, destination, "--offset", "4", "--length", "6"))

	if fixture.status != 0 {
		t.Fatalf("status = %d, want 0; stderr = %q", fixture.status, fixture.stderr)
	}
	written, err := os.ReadFile(destination)
	if err != nil {
		t.Fatalf("read the destination: %v", err)
	}
	if string(written) != "456789" {
		t.Errorf("destination = %q, want %q", written, "456789")
	}
}

// TestRawReadLeavesNoPartialFileOnFailure proves a failure on the second chunk leaves
// no file behind.
func TestRawReadLeavesNoPartialFileOnFailure(t *testing.T) {
	content := make([]byte, 2*capBytes)
	state, url := newRawServer(t, content)
	state.omitTruncated = true

	destination := filepath.Join(t.TempDir(), "out.bin")
	fixture := runAgainst(t, url, outputArguments(t, destination))

	if fixture.status == 0 {
		t.Fatalf("status = 0, want a refusal")
	}
	entries, err := os.ReadDir(filepath.Dir(destination))
	if err != nil {
		t.Fatalf("read the directory: %v", err)
	}
	for _, entry := range entries {
		t.Errorf("the directory holds %q after a failure, want nothing", entry.Name())
	}
}

// TestStdoutReadUsesTheRawPath proves the single-chunk stdout read also opts in.
//
// It is the most common invocation, so leaving it on the envelope would keep the
// encoding cost on the path most callers use.
func TestStdoutReadUsesTheRawPath(t *testing.T) {
	content := []byte("hello, connector")
	state, url := newRawServer(t, content)

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
	if fixture.stdout != string(content) {
		t.Errorf("stdout = %q, want %q", fixture.stdout, content)
	}
	state.mu.Lock()
	accepts := append([]string(nil), state.accepts...)
	state.mu.Unlock()
	if len(accepts) != 1 {
		t.Fatalf("requests = %d, want 1", len(accepts))
	}
	if !strings.Contains(accepts[0], rawContentMediaType) {
		t.Errorf("Accept = %q, want %q", accepts[0], rawContentMediaType)
	}
}

// TestJsonReadKeepsTheEnvelope proves `--json` does not opt in.
//
// The flag asks for the envelope, and a raw body is not JSON, so opting in would print
// something no parser accepts.
func TestJsonReadKeepsTheEnvelope(t *testing.T) {
	content := []byte("hello, connector")
	state, url := newRawServer(t, content)

	arguments := []string{
		"--client-credential", testClientCredential().String(),
		"--node-credential", testNodeCredential().String(),
		"--node-id", testNodeID(t),
		"--scope", "project",
		"--path", "a.bin",
		"--json",
		"file.read",
	}
	fixture := runAgainst(t, url, arguments)

	if fixture.status != 0 {
		t.Fatalf("status = %d, want 0; stderr = %q", fixture.status, fixture.stderr)
	}
	state.mu.Lock()
	accepts := append([]string(nil), state.accepts...)
	state.mu.Unlock()
	for index, accept := range accepts {
		if strings.Contains(accept, rawContentMediaType) {
			t.Errorf("request %d Accept = %q, want no opt-in under --json", index, accept)
		}
	}
	var envelope Envelope
	if err := json.Unmarshal([]byte(fixture.stdout), &envelope); err != nil {
		t.Fatalf("stdout is not an envelope: %v; stdout = %q", err, fixture.stdout)
	}
	if !envelope.Succeeded() {
		t.Errorf("code = %d, want success", envelope.Code)
	}
}

// TestListAndStatDoNotOptIn proves the other two operations keep the envelope.
//
// They have no byte stream to opt into, and a raw answer would be unprintable.
func TestListAndStatDoNotOptIn(t *testing.T) {
	for _, operation := range []string{"file.list", "file.stat"} {
		t.Run(operation, func(t *testing.T) {
			var mu sync.Mutex
			var accepts []string
			server := httptest.NewServer(http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
				mu.Lock()
				accepts = append(accepts, request.Header.Get("Accept"))
				mu.Unlock()
				writer.Header().Set("Content-Type", "application/json")
				_, _ = writer.Write([]byte(`{"code":0,"message":"success","data":{"entries":[]},"request_id":"req_1","timestamp":1}`))
			}))
			t.Cleanup(server.Close)

			arguments := []string{
				"--client-credential", testClientCredential().String(),
				"--node-credential", testNodeCredential().String(),
				"--node-id", testNodeID(t),
				"--scope", "project",
				"--path", "a.bin",
				operation,
			}
			fixture := runAgainst(t, server.URL, arguments)
			if fixture.status != 0 {
				t.Fatalf("status = %d, want 0; stderr = %q", fixture.status, fixture.stderr)
			}
			mu.Lock()
			seen := append([]string(nil), accepts...)
			mu.Unlock()
			for index, accept := range seen {
				if strings.Contains(accept, rawContentMediaType) {
					t.Errorf("request %d Accept = %q, want no opt-in for %s", index, accept, operation)
				}
			}
		})
	}
}
