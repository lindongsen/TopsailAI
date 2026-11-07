package tui

import (
	"io"
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

// fullLayoutSessionID exceeds the SESSION_ID cap, so a bounded layout must clip
// it while a full layout must keep every character.
func fullLayoutSessionID() string {
	return "session-" + strings.Repeat("0123456789", 6)
}

// TestFullLayoutKeepsEverySessionValue proves the full layout ignores both the
// terminal bound and the per-column caps, so a narrow terminal wraps instead of
// losing data.
func TestFullLayoutKeepsEverySessionValue(t *testing.T) {
	sessionID := fullLayoutSessionID()
	endpointID := "endpoint-" + strings.Repeat("abcdefghij", 4)
	rows := []SessionRow{{EndpointID: endpointID, ProviderSessionID: sessionID, State: "running"}}
	var out strings.Builder
	if err := RenderTable(&out, io.Discard, rows, nil, TableOptions{Width: 40, Full: true}); err != nil {
		t.Fatal(err)
	}
	rendered := out.String()
	if !strings.Contains(rendered, sessionID) {
		t.Fatalf("session id was truncated: %q", rendered)
	}
	if !strings.Contains(rendered, endpointID) {
		t.Fatalf("endpoint id was truncated: %q", rendered)
	}
	if strings.Contains(rendered, "...") {
		t.Fatalf("full layout emitted a truncation marker: %q", rendered)
	}
}

// TestBoundedLayoutStillTruncates proves the switch is opt-in: the default
// layout keeps clipping the same values.
func TestBoundedLayoutStillTruncates(t *testing.T) {
	sessionID := fullLayoutSessionID()
	rows := []SessionRow{{EndpointID: "ep", ProviderSessionID: sessionID, State: "running"}}
	var out strings.Builder
	if err := RenderTable(&out, io.Discard, rows, nil, TableOptions{Width: 40}); err != nil {
		t.Fatal(err)
	}
	if strings.Contains(out.String(), sessionID) {
		t.Fatalf("bounded layout kept the over-cap value: %q", out.String())
	}
}

// TestFullLayoutKeepsEveryEndpointValue proves the endpoint table honours the
// same switch, so both projections share one truncation policy.
func TestFullLayoutKeepsEveryEndpointValue(t *testing.T) {
	hostname := "host-" + strings.Repeat("q", 60)
	revision := "rev-" + strings.Repeat("9", 40)
	endpoints := []protocol.Endpoint{{EndpointID: "ep-1", Hostname: hostname, CapabilityRevision: revision, ConnectionState: "online"}}
	var out strings.Builder
	if err := RenderEndpoints(&out, endpoints, "", false, TableOptions{Width: 40, Full: true}); err != nil {
		t.Fatal(err)
	}
	rendered := out.String()
	if !strings.Contains(rendered, hostname) || !strings.Contains(rendered, revision) {
		t.Fatalf("endpoint values were truncated: %q", rendered)
	}
	if strings.Contains(rendered, "...") {
		t.Fatalf("full layout emitted a truncation marker: %q", rendered)
	}
}

// TestFullLayoutKeepsRealTerminalWidth proves the boundary still reports the
// real width, so the interactive prompt editor keeps its budget.
func TestFullLayoutKeepsRealTerminalWidth(t *testing.T) {
	out := &fullLayoutOutput{width: 120, full: true}
	layout := OutputLayout(out)
	if layout.Width != 120 || !layout.Full {
		t.Fatalf("layout=%+v", layout)
	}
	if OutputWidth(out) != 120 {
		t.Fatalf("width=%d", OutputWidth(out))
	}
	options := TableOptionsFor(out)
	if options.Width != 120 || !options.Full {
		t.Fatalf("options=%+v", options)
	}
}

// TestOutputLayoutDefaultsToTruncation proves a writer that only reports a width
// keeps the bounded layout, so existing boundaries are unaffected.
func TestOutputLayoutDefaultsToTruncation(t *testing.T) {
	layout := OutputLayout(&sizedTableOutput{width: 90})
	if layout.Width != 90 || layout.Full {
		t.Fatalf("layout=%+v", layout)
	}
	if options := TableOptionsFor(io.Discard); options.Width != 0 || options.Full {
		t.Fatalf("options=%+v", options)
	}
}

// fullLayoutOutput reports both the terminal width and the truncation policy.
type fullLayoutOutput struct {
	strings.Builder
	width int
	full  bool
}

// TerminalWidth exposes the injected terminal width.
func (out *fullLayoutOutput) TerminalWidth() int { return out.width }

// TableLayout exposes the injected presentation policy.
func (out *fullLayoutOutput) TableLayout() TableLayout {
	return TableLayout{Width: out.width, Full: out.full}
}

// TestFullLayoutStillSanitizes proves the switch only disables truncation: a
// hostile value is still stripped of terminal control sequences.
func TestFullLayoutStillSanitizes(t *testing.T) {
	hostile := "session-\x1b[2J\x1b]0;pwned\x07" + strings.Repeat("x", 60)
	rows := []SessionRow{{EndpointID: "ep", ProviderSessionID: hostile, State: "running"}}
	var out strings.Builder
	if err := RenderTable(&out, io.Discard, rows, nil, TableOptions{Width: 40, Full: true}); err != nil {
		t.Fatal(err)
	}
	rendered := out.String()
	if strings.Contains(rendered, "\x1b") {
		t.Fatalf("full layout leaked a control sequence: %q", rendered)
	}
	if !strings.Contains(rendered, strings.Repeat("x", 60)) {
		t.Fatalf("full layout dropped the printable tail: %q", rendered)
	}
}
