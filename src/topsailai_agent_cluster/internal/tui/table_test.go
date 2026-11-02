package tui

import (
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

func TestTableColumnsWidthsAndEmptyResult(t *testing.T) {
	var out, errors strings.Builder
	stamp := int64(1700000000000)
	rows := []SessionRow{{EndpointID: "endpoint-1", AdapterID: "adapter", SessionID: strings.Repeat("s", 60), Generation: "generation", State: "running", LastSuccessAtMS: &stamp, CollectionStatus: protocol.CollectionSucceeded}}
	if err := RenderTable(&out, &errors, rows, nil, TableOptions{}); err != nil {
		t.Fatal(err)
	}
	lines := strings.Split(strings.TrimSuffix(out.String(), "\n"), "\n")
	if !strings.HasPrefix(lines[0], "NO") || !strings.Contains(lines[0], "  ADAPTER") || !strings.Contains(lines[0], "  SESSION") || !strings.HasSuffix(lines[0], "LAST_SUCCESS_MS") {
		t.Fatalf("header=%q", lines[0])
	}
	if len(lines[1]) > 165 || !strings.Contains(lines[1], "...") {
		t.Fatalf("bounded row=%q len=%d", lines[1], len(lines[1]))
	}
	if !strings.HasSuffix(lines[1], "1700000000000") {
		t.Fatalf("timestamp not right aligned: %q", lines[1])
	}
	out.Reset()
	if err := RenderTable(&out, &errors, nil, nil, TableOptions{}); err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(out.String(), "no sessions\n") {
		t.Fatalf("empty output=%q", out.String())
	}
}

func TestTableEscapesCellsAndReportsPartialFailures(t *testing.T) {
	var out, errors strings.Builder
	rows := []SessionRow{{EndpointID: "good", State: "running", CollectionStatus: protocol.CollectionSucceeded}}
	failures := []EndpointFailure{{EndpointID: "bad", Err: errTableFixture}}
	if err := RenderTable(&out, &errors, rows, failures, TableOptions{}); err != nil {
		t.Fatal(err)
	}
	if strings.ContainsAny(out.String(), "\x1b\r\n\t") && strings.Count(out.String(), "\n") == 0 {
		t.Fatal("unexpected control output")
	}
	if !strings.Contains(errors.String(), "endpoint bad unavailable: fixture failure") {
		t.Fatalf("errors=%q", errors.String())
	}
	if !strings.Contains(out.String(), "good") || strings.Contains(out.String(), "bad") {
		t.Fatalf("partial table=%q", out.String())
	}
	if got := escapeCell("a\n\t\x1b\u202eé"); got != `a\u000A\u0009\u001B\u202E\u00E9` {
		t.Fatalf("escaped=%q", got)
	}
}

var errTableFixture = tableFixtureError{}

type tableFixtureError struct{}

func (tableFixtureError) Error() string { return "fixture failure" }

func TestColorPolicyMatrixAndPrompt(t *testing.T) {
	if ResolveColorPolicy(true, true, false, false, true).Enabled {
		t.Fatal("NO_COLOR presence must disable color")
	}
	if ResolveColorPolicy(true, false, false, false, true).Enabled == false {
		t.Fatal("eligible tty must enable color")
	}
	var out strings.Builder
	if err := RenderPrompt(&out, "endpoint", "session", false, ColorPolicy{Enabled: true}); err != nil {
		t.Fatal(err)
	}
	got := out.String()
	for _, token := range []string{"\x1b[1;36m", "\x1b[36m", "\x1b[1;32m", "\x1b[0m"} {
		if !strings.Contains(got, token) {
			t.Fatalf("prompt missing %q: %q", token, got)
		}
	}
	if !strings.HasSuffix(got, "\x1b[0m ") {
		t.Fatalf("prompt does not reset before space: %q", got)
	}
	out.Reset()
	if err := RenderPrompt(&out, "endpoint", "session", true, ColorPolicy{Enabled: true}); err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(out.String(), "\x1b[31m") {
		t.Fatalf("invalid prompt not red: %q", out.String())
	}
}

func TestPromptEscapesUntrustedControlText(t *testing.T) {
	var out strings.Builder
	if err := RenderPrompt(&out, "ep\n\x1b[31m", "session\t1", false, ColorPolicy{Enabled: true}); err != nil {
		t.Fatal(err)
	}
	if strings.ContainsAny(out.String(), "\n\t") || strings.Contains(out.String(), "\x1b[31mep") {
		t.Fatalf("untrusted prompt content leaked: %q", out.String())
	}
}

func TestTableJSONHasNoPresentationBytes(t *testing.T) {
	var out strings.Builder
	stamp := int64(1700000000000)
	rows := []SessionRow{{EndpointID: "ep", SessionID: "session", State: "running", LastSuccessAtMS: &stamp}}
	if err := RenderJSON(&out, rows); err != nil {
		t.Fatal(err)
	}
	if strings.Contains(out.String(), "\x1b") || strings.Contains(out.String(), "ENDPOINT") {
		t.Fatalf("json contaminated: %q", out.String())
	}
}
