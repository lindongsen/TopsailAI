package tui

import (
	"encoding/json"
	"strings"
	"testing"
	"time"
	"unicode/utf8"

	"topsailai_agent_cluster/internal/protocol"
)

func TestTableColumnsWidthsAndEmptyResult(t *testing.T) {
	var out, errors strings.Builder
	stamp := int64(1700000000000)
	rows := []SessionRow{{EndpointID: "endpoint-1", AdapterID: "adapter", SessionID: "res_opaque", ProviderSessionID: strings.Repeat("p", 60), Generation: "generation", State: "running", LastSuccessAtMS: &stamp, CollectionStatus: protocol.CollectionSucceeded}}
	if err := RenderTable(&out, &errors, rows, nil, TableOptions{Location: time.UTC}); err != nil {
		t.Fatal(err)
	}
	lines := strings.Split(strings.TrimSuffix(out.String(), "\n"), "\n")
	headerCells := strings.Split(lines[0], " │ ")
	if len(headerCells) != 8 {
		t.Fatalf("header cell count=%d header=%q", len(headerCells), lines[0])
	}
	for index, want := range []string{"NO", "ENDPOINT", "ADAPTER", "SESSION_NAME", "SESSION_ID", "SESSION_STATUS", "DATA_STATUS", "LAST_SUCCESS"} {
		if strings.TrimSpace(headerCells[index]) != want {
			t.Fatalf("header cell %d=%q want=%q", index, headerCells[index], want)
		}
	}
	if strings.Contains(lines[0], "GENERATION") || strings.Contains(lines[0], "LAST_SUCCESS_MS") {
		t.Fatalf("header still has removed columns: %q", lines[0])
	}
	if !strings.Contains(lines[1], "─┼─") {
		t.Fatalf("missing header separator=%q", lines[1])
	}
	if len(lines[2]) > 190 || !strings.Contains(lines[2], "...") {
		t.Fatalf("bounded row=%q len=%d", lines[2], len(lines[2]))
	}
	if !strings.HasSuffix(lines[2], "2023-11-14 22:13:20") {
		t.Fatalf("timestamp not right aligned: %q", lines[2])
	}
	out.Reset()
	if err := RenderTable(&out, &errors, nil, nil, TableOptions{}); err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(out.String(), "no sessions\n") {
		t.Fatalf("empty output=%q", out.String())
	}
}

func TestTableStateColors(t *testing.T) {
	cases := []struct {
		state string
		style string
	}{
		{"running", ansiGreen},
		{"failed", ansiRed},
		{"stopped", ansiDim},
		{"unknown-state", ansiYellow},
	}
	for _, testCase := range cases {
		var out, errors strings.Builder
		rows := []SessionRow{{EndpointID: "ep", State: testCase.state}}
		if err := RenderTable(&out, &errors, rows, nil, TableOptions{Color: ColorPolicy{Enabled: true}}); err != nil {
			t.Fatal(err)
		}
		if !strings.Contains(out.String(), testCase.style) {
			t.Fatalf("state %q missing style %q: %q", testCase.state, testCase.style, out.String())
		}
	}
	var plain, errors strings.Builder
	if err := RenderTable(&plain, &errors, []SessionRow{{EndpointID: "ep", State: "running"}}, nil, TableOptions{}); err != nil {
		t.Fatal(err)
	}
	if strings.Contains(plain.String(), "\x1b[") || !strings.Contains(plain.String(), " │ ") {
		t.Fatalf("no-color rendering=%q", plain.String())
	}
}

func TestTablePreservesPrintableUnicodeAndReportsPartialFailures(t *testing.T) {
	var out, errors strings.Builder
	rows := []SessionRow{{EndpointID: "good", State: "running", CollectionStatus: protocol.CollectionSucceeded}}
	failures := []EndpointFailure{{EndpointID: "bad", Err: errTableFixture}}
	if err := RenderTable(&out, &errors, rows, failures, TableOptions{}); err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(errors.String(), "endpoint bad unavailable: fixture failure") {
		t.Fatalf("errors=%q", errors.String())
	}
	if !strings.Contains(out.String(), "good") || strings.Contains(out.String(), "bad") {
		t.Fatalf("partial table=%q", out.String())
	}
	got := escapeCell("统一Agent管理方案 √©")
	if got != "统一Agent管理方案 √©" || strings.Contains(got, `\\u`) {
		t.Fatalf("printable Unicode escaped: %q", got)
	}
	if got := escapeCell("a\n\t"); got != "a��" {
		t.Fatalf("control cell=%q", got)
	}
	if got := escapeCell("\x1b[31m\u202e\u200b"); got != "" {
		t.Fatalf("unsafe cell=%q", got)
	}
}

func TestTableUsesCJKDisplayWidthAndRuneSafeClip(t *testing.T) {
	if got := displayWidth("中a"); got != 3 {
		t.Fatalf("displayWidth=%d want=3", got)
	}
	clipped := clipCell("中文字符", 6)
	if clipped != "中..." || !utf8.ValidString(clipped) {
		t.Fatalf("clipped=%q", clipped)
	}

}

func TestDataStatusCoversCollectionAndFreshnessCombinations(t *testing.T) {
	collections := []struct {
		collection string
		base       string
	}{
		{protocol.CollectionSucceeded, "ok"},
		{protocol.CollectionFailed, "failed"},
		{protocol.CollectionPartial, "partial"},
		{protocol.CollectionUnknown, "unknown"},
	}
	for _, testCase := range collections {
		for _, flags := range []struct {
			stale, unknown bool
			suffix         string
		}{
			{false, false, ""},
			{true, false, "/stale"},
			{false, true, "/unknown"},
			{true, true, "/unknown+stale"},
		} {
			row := SessionRow{CollectionStatus: testCase.collection, Stale: flags.stale, Unknown: flags.unknown}
			want := testCase.base + flags.suffix
			if got := dataStatus(row); got != want {
				t.Fatalf("collection=%q stale=%t unknown=%t: got %q want %q", testCase.collection, flags.stale, flags.unknown, got, want)
			}
		}
	}
	if got := dataStatus(SessionRow{CollectionStatus: ""}); got != "unrecognized" {
		t.Fatalf("empty collection status = %q", got)
	}
	if got := dataStatus(SessionRow{CollectionStatus: "unexpected", Stale: true, Unknown: true}); got != "unrecognized/unknown+stale" {
		t.Fatalf("unexpected collection status = %q", got)
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

	tests := []struct {
		name      string
		scope     ScopeState
		invalid   bool
		plainWant string
	}{
		{name: "idle", plainWant: "workspace> "},
		{name: "endpoint", scope: ScopeState{Kind: ScopeEndpoint, EndpointID: "endpoint-1", Hostname: "ai-dev"}, plainWant: "endpoint[ai-dev/endpoint-1]> "},
		{name: "endpoint fallback", scope: ScopeState{Kind: ScopeEndpoint, EndpointID: "endpoint-1"}, plainWant: "endpoint[endpoint-1]> "},
		{name: "session fallback", scope: ScopeState{Kind: ScopeSession, EndpointID: "endpoint-1", SessionID: "session"}, plainWant: "session[endpoint-1/-]> "},
		{name: "selected", scope: ScopeState{Kind: ScopeSession, EndpointID: "endpoint", Hostname: "endpoint", SessionID: "session"}, plainWant: "session[endpoint/-]> "},
		{name: "invalidated", scope: ScopeState{Kind: ScopeSession, EndpointID: "endpoint", Hostname: "endpoint", SessionID: "session"}, invalid: true, plainWant: "session[endpoint/-!]> "},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			var colored, plain strings.Builder
			if err := RenderPrompt(&colored, test.scope, test.invalid, ColorPolicy{Enabled: true}); err != nil {
				t.Fatal(err)
			}
			got := colored.String()
			want := ansiBoldGreen + test.plainWant[:len(test.plainWant)-1] + ansiReset + " "
			if got != want {
				t.Fatalf("colored prompt = %q, want %q", got, want)
			}
			if strings.Contains(got, ansiCyan) || strings.Contains(got, ansiBoldCyan) {
				t.Fatalf("prompt contains cyan styling: %q", got)
			}
			if !strings.HasSuffix(got, ansiReset+" ") {
				t.Fatalf("prompt does not reset before space: %q", got)
			}
			if err := RenderPrompt(&plain, test.scope, test.invalid, ColorPolicy{}); err != nil {
				t.Fatal(err)
			}
			if plain.String() != test.plainWant {
				t.Fatalf("plain prompt = %q, want %q", plain.String(), test.plainWant)
			}
		})
	}
}

func TestPromptEscapesUntrustedControlText(t *testing.T) {
	var out strings.Builder
	if err := RenderPrompt(&out, ScopeState{Kind: ScopeSession, EndpointID: "ep\n\x1b[31m", Hostname: "ep\n\x1b[31m", SessionID: "session\t1"}, false, ColorPolicy{Enabled: true}); err != nil {
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

func TestTableJSONPreservesMachineFields(t *testing.T) {
	stamp := int64(1700000000000)
	rows := []SessionRow{{EndpointID: "ep", SessionID: "res_opaque", ProviderSessionID: "provider-42", Generation: "gen-7", LastSuccessAtMS: &stamp}}
	var out strings.Builder
	if err := RenderJSON(&out, rows); err != nil {
		t.Fatal(err)
	}
	var decoded []map[string]any
	if err := json.Unmarshal([]byte(out.String()), &decoded); err != nil {
		t.Fatal(err)
	}
	if decoded[0]["generation"] != "gen-7" {
		t.Fatalf("generation = %#v", decoded[0]["generation"])
	}
	if got, ok := decoded[0]["last_success_at_ms"].(float64); !ok || got != float64(stamp) {
		t.Fatalf("last_success_at_ms = %#v", decoded[0]["last_success_at_ms"])
	}
}

func TestTableUsesSeparateSessionNameAndProviderIDColumns(t *testing.T) {
	stamp := int64(1700000000000)
	rows := []SessionRow{{No: 1, EndpointID: "ep", SessionID: "res_opaque", ProviderSessionID: "provider-42", DisplayName: "Daily work", State: "running", LastSuccessAtMS: &stamp, CollectionStatus: protocol.CollectionSucceeded}}
	var out, errors strings.Builder
	if err := RenderTable(&out, &errors, rows, nil, TableOptions{Location: time.UTC}); err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(out.String(), "Daily work") || strings.Contains(out.String(), "res_opaque") {
		t.Fatalf("display name output = %q", out.String())
	}
	out.Reset()
	rows[0].DisplayName = ""
	if err := RenderTable(&out, &errors, rows, nil, TableOptions{Location: time.UTC}); err != nil {
		t.Fatal(err)
	}
	if strings.Contains(out.String(), "res_opaque") || !strings.Contains(out.String(), "provider-42") {
		t.Fatalf("separate provider ID output = %q", out.String())
	}
	if strings.Contains(out.String(), "Daily work") {
		t.Fatalf("session name fallback output = %q", out.String())
	}
	out.Reset()
	rows[0].ProviderSessionID = ""
	if err := RenderTable(&out, &errors, rows, nil, TableOptions{Location: time.UTC}); err != nil {
		t.Fatal(err)
	}
	if strings.Contains(out.String(), "res_opaque") || strings.Contains(out.String(), "provider-42") {
		t.Fatalf("empty session fields output = %q", out.String())
	}
}

func TestTableNilLastSuccessDisplaysDash(t *testing.T) {
	var out, errors strings.Builder
	rows := []SessionRow{{EndpointID: "ep", AdapterID: "adapter", ProviderSessionID: "provider", State: "running", CollectionStatus: protocol.CollectionSucceeded}}
	if err := RenderTable(&out, &errors, rows, nil, TableOptions{Location: time.FixedZone("CST", 8*3600)}); err != nil {
		t.Fatal(err)
	}
	lines := strings.Split(strings.TrimSuffix(out.String(), "\n"), "\n")
	cells := strings.Split(lines[2], " │ ")
	if got := strings.TrimSpace(cells[columnLastSuccess]); got != "-" {
		t.Fatalf("LAST_SUCCESS cell = %q, want %q; row=%q", got, "-", lines[2])
	}
}

func TestTableLastSuccessUsesNonUTCOffset(t *testing.T) {
	stamp := int64(1700000000000)
	rows := []SessionRow{{EndpointID: "ep", ProviderSessionID: "provider", LastSuccessAtMS: &stamp}}
	var out, errors strings.Builder
	location := time.FixedZone("CST", 8*3600)
	if err := RenderTable(&out, &errors, rows, nil, TableOptions{Location: location}); err != nil {
		t.Fatal(err)
	}
	lines := strings.Split(strings.TrimSuffix(out.String(), "\n"), "\n")
	cells := strings.Split(lines[2], " │ ")
	if got := cells[columnLastSuccess]; got != "2023-11-15 06:13:20" {
		t.Fatalf("LAST_SUCCESS cell = %q, want %q; row=%q", got, "2023-11-15 06:13:20", lines[2])
	}
}
