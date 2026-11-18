package providerconformance

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// repoText reads one file from the repository root so a guard can assert what
// the shipped protocol and Provider sources say rather than restating it.
func repoText(t *testing.T, parts ...string) string {
	t.Helper()
	path := filepath.Join(append([]string{"..", ".."}, parts...)...)
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("read %s: %v", path, err)
	}
	return string(data)
}

// TestRequestSchemaHasNoFaultProperty proves a remote caller cannot select a
// fault mode through the request envelope. The envelope is closed
// (additionalProperties false), so a field absent from its property set is
// rejected by every Provider that decodes strictly. A fault selector added here
// would let any remote caller choose how the Provider misbehaves.
func TestRequestSchemaHasNoFaultProperty(t *testing.T) {
	raw := repoText(t, "protocol", "provider-cli", "v1", "request.schema.json")
	var schema struct {
		AdditionalProperties *bool                  `json:"additionalProperties"`
		Properties           map[string]interface{} `json:"properties"`
	}
	if err := json.Unmarshal([]byte(raw), &schema); err != nil {
		t.Fatalf("decode request.schema.json: %v", err)
	}
	if schema.AdditionalProperties == nil || *schema.AdditionalProperties {
		t.Fatalf("request.schema.json is not closed, so an unknown field such as fault_mode would be accepted")
	}
	if len(schema.Properties) == 0 {
		t.Fatalf("request.schema.json declares no properties, so the guard is reading the wrong document")
	}
	for name := range schema.Properties {
		if strings.Contains(strings.ToLower(name), "fault") {
			t.Fatalf("request.schema.json declares the property %q, so a remote caller can select a fault mode", name)
		}
	}
}

// TestNoSchemaDeclaresAFaultProperty proves no protocol schema carries a fault
// selector. The request envelope is the only document a remote caller controls,
// but a fault field added to a payload schema would be just as reachable.
func TestNoSchemaDeclaresAFaultProperty(t *testing.T) {
	dir := filepath.Join("..", "..", "protocol", "provider-cli", "v1")
	entries, err := os.ReadDir(dir)
	if err != nil {
		t.Fatalf("read %s: %v", dir, err)
	}
	scanned := 0
	for _, entry := range entries {
		if entry.IsDir() || !strings.HasSuffix(entry.Name(), ".schema.json") {
			continue
		}
		scanned++
		raw := repoText(t, "protocol", "provider-cli", "v1", entry.Name())
		if strings.Contains(strings.ToLower(raw), "fault") {
			t.Fatalf("%s mentions fault, so a fault selector reached the protocol", entry.Name())
		}
	}
	if scanned == 0 {
		t.Fatalf("no schema files were scanned, so the guard proved nothing")
	}
}

// TestMockDecodesTheRequestStrictly proves the Mock Provider rejects an unknown
// request field instead of ignoring it. Without strict decoding a fault_mode
// field would be silently dropped, which looks like a refusal but leaves the
// envelope open for the next field.
func TestMockDecodesTheRequestStrictly(t *testing.T) {
	source := repoText(t, "providers", "mock", "src", "main.go")
	if !strings.Contains(source, "decoder.DisallowUnknownFields()") {
		t.Fatalf("providers/mock/src/main.go does not decode the request strictly, so an unknown field is ignored")
	}
	if !strings.Contains(source, "func decodeRequest(") {
		t.Fatalf("providers/mock/src/main.go has no decodeRequest, so the guard is reading the wrong file")
	}
}

// TestMockFaultSelectionIsLocalOnly proves the Mock Provider takes its fault
// from argv and the environment, never from the request document. argv and the
// environment are controlled by whoever launches the process; the request is
// controlled by the remote caller, so a fault read from the request would be a
// remote fault selector.
func TestMockFaultSelectionIsLocalOnly(t *testing.T) {
	source := repoText(t, "providers", "mock", "src", "main.go")
	if !strings.Contains(source, `flag.StringVar(&options.fault, "fault"`) {
		t.Fatalf("providers/mock/src/main.go does not read the fault from argv, so the harness cannot inject one")
	}
	if !strings.Contains(source, "os.Getenv(faultEnvironment)") {
		t.Fatalf("providers/mock/src/main.go does not read the fault from the environment, so the documented channel is gone")
	}
	if strings.Contains(source, "request.Fault") {
		t.Fatalf("providers/mock/src/main.go reads a fault from the request, so a remote caller can select one")
	}
}

// TestRealProviderAlsoDecodesStrictly proves the shipped Provider is not more
// permissive than the Mock. A strict Mock beside a lenient real Provider would
// leave the production path open while the conformance suite stayed green.
func TestRealProviderAlsoDecodesStrictly(t *testing.T) {
	source := repoText(t, "providers", "topsailai", "src", "provider.go")
	if !strings.Contains(source, "decoder.DisallowUnknownFields()") {
		t.Fatalf("providers/topsailai/src/provider.go does not decode the request strictly, so the production path accepts unknown fields")
	}
}
