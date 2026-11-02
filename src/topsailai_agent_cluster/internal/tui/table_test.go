package tui

import (
	"strings"
	"testing"
	"unicode/utf8"

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
	if !strings.HasPrefix(lines[0], "NO") || !strings.Contains(lines[0], " │ ADAPTER") || !strings.Contains(lines[0], " │ SESSION") || !strings.HasSuffix(lines[0], "LAST_SUCCESS_MS") {
		t.Fatalf("header=%q", lines[0])
	}
	if !strings.Contains(lines[1], "─┼─") {
		t.Fatalf("missing header separator=%q", lines[1])
	}
	if len(lines[2]) > 190 || !strings.Contains(lines[2], "...") {
		t.Fatalf("bounded row=%q len=%d", lines[2], len(lines[2]))
	}
	if !strings.HasSuffix(lines[2], "1700000000000") {
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
		endpoint  string
		session   string
		invalid   bool
		plainWant string
	}{
		{name: "idle", plainWant: "cluster> "},
		{name: "selected", endpoint: "endpoint", session: "session", plainWant: "cluster[endpoint/session]> "},
		{name: "invalidated", endpoint: "endpoint", session: "session", invalid: true, plainWant: "cluster[endpoint/session!]> "},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			var colored, plain strings.Builder
			if err := RenderPrompt(&colored, test.endpoint, test.session, test.invalid, ColorPolicy{Enabled: true}); err != nil {
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
			if err := RenderPrompt(&plain, test.endpoint, test.session, test.invalid, ColorPolicy{}); err != nil {
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

func TestTableUsesSessionDisplayNameAndFallsBackToID(t *testing.T) {
	stamp := int64(1700000000000)
	rows := []SessionRow{{No: 1, EndpointID: "ep", SessionID: "res_opaque", DisplayName: "Daily work", State: "running", LastSuccessAtMS: &stamp, CollectionStatus: protocol.CollectionSucceeded}}
	var out, errors strings.Builder
	if err := RenderTable(&out, &errors, rows, nil, TableOptions{}); err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(out.String(), "Daily work") || strings.Contains(out.String(), "res_opaque") {
		t.Fatalf("display name output = %q", out.String())
	}
	out.Reset()
	rows[0].DisplayName = ""
	if err := RenderTable(&out, &errors, rows, nil, TableOptions{}); err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(out.String(), "res_opaque") {
		t.Fatalf("fallback output = %q", out.String())
	}
}
