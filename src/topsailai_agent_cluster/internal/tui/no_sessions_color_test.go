package tui

import (
	"io"
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

// noSessionsRow builds the placeholder row ListRows appends for an Endpoint that
// reported an empty inventory.
func noSessionsRow() SessionRow {
	return SessionRow{EndpointID: "endpoint-1", EndpointLabel: "endpoint-1", State: stateNoSessions, CollectionStatus: protocol.CollectionSucceeded}
}

// TestNoSessionsPlaceholderIsDim proves the placeholder row for an Endpoint with
// nothing to show is dim rather than yellow.
//
// Yellow means "uncertain, needs a look", so a healthy Endpoint that reported an
// empty inventory used to read as a condition the operator had to investigate.
// An empty inventory is a definite answer, so the row belongs to the dim family
// with the other states where nothing is running and nothing has failed.
//
// The summary line is asserted too, because it reads the same mapping: a change
// that coloured only the row would leave the line contradicting it.
func TestNoSessionsPlaceholderIsDim(t *testing.T) {
	rows := []SessionRow{noSessionsRow()}
	var colored, errors strings.Builder
	if err := RenderTable(&colored, &errors, rows, nil, TableOptions{Color: ColorPolicy{Enabled: true}}); err != nil {
		t.Fatal(err)
	}
	rendered := colored.String()
	row := dataRowLine(t, rendered)
	if !strings.Contains(row, ansiDim) {
		t.Fatalf("placeholder row must be dim, got %q", row)
	}
	if strings.Contains(row, ansiYellow) {
		t.Fatalf("placeholder row must not be yellow, got %q", row)
	}
	// Every cell and separator of the row carries the dim style, so no cell is
	// left in the default colour.
	for _, sequence := range sgrSequences(row) {
		if sequence != ansiDim && sequence != ansiReset {
			t.Fatalf("placeholder row contains foreign style %q: %q", sequence, row)
		}
	}
	if !strings.Contains(rendered, ansiDim+stateNoSessions+"(1)"+ansiReset) {
		t.Fatalf("summary line must colour the placeholder bucket dim, got %q", rendered)
	}
}

// TestNoSessionsPlaceholderIsDimInNarrowLayout proves the narrow layout agrees
// with the wide one. The two layouts colour through separate writers, so a
// mapping change that reached only one of them would leave the same row two
// different colours depending on the terminal width.
func TestNoSessionsPlaceholderIsDimInNarrowLayout(t *testing.T) {
	rows := []SessionRow{noSessionsRow()}
	var colored strings.Builder
	options := TableOptions{Width: narrowProbeWidth(), Color: ColorPolicy{Enabled: true}}
	if err := RenderTable(&colored, io.Discard, rows, nil, options); err != nil {
		t.Fatal(err)
	}
	blocks := narrowFieldBlocks(t, colored.String())
	if len(blocks) != 1 {
		t.Fatalf("blocks = %d, want 1: %q", len(blocks), colored.String())
	}
	for _, line := range blocks[0] {
		if !strings.Contains(line, ansiDim) {
			t.Fatalf("narrow field line lost the dim colour: %q", line)
		}
		if strings.Contains(line, ansiYellow) {
			t.Fatalf("narrow field line must not be yellow: %q", line)
		}
	}
}

// TestNoSessionsPlaceholderKeepsPlainBytes proves the change is colour-only. A
// redirected stream and a --no-color run must stay byte-identical, so the
// placeholder text and the summary text are unchanged.
func TestNoSessionsPlaceholderKeepsPlainBytes(t *testing.T) {
	rows := []SessionRow{noSessionsRow()}
	var plain, errors strings.Builder
	if err := RenderTable(&plain, &errors, rows, nil, TableOptions{}); err != nil {
		t.Fatal(err)
	}
	rendered := plain.String()
	if strings.Contains(rendered, "\x1b[") {
		t.Fatalf("plain render must carry no escape sequence: %q", rendered)
	}
	if !strings.Contains(rendered, stateNoSessions) {
		t.Fatalf("plain render lost the placeholder text: %q", rendered)
	}
	if !strings.Contains(rendered, stateNoSessions+"(1)") {
		t.Fatalf("plain render lost the summary bucket: %q", rendered)
	}
}

// TestNoSessionsColourIsScopedToThePlaceholder proves the default branch keeps
// its meaning. An unrecognized state must still be yellow, so the change adds one
// value to the dim family instead of recolouring the fallback that exists to make
// an unknown value visible.
func TestNoSessionsColourIsScopedToThePlaceholder(t *testing.T) {
	if got := stateStyle(stateNoSessions); got != ansiDim {
		t.Fatalf("placeholder colour = %q, want dim %q", got, ansiDim)
	}
	if got := stateStyle("unknown-state"); got != ansiYellow {
		t.Fatalf("unrecognized state colour = %q, want yellow %q", got, ansiYellow)
	}
	// The placeholder is a presentation value, never a session state, so it must
	// not appear in the state vocabulary the protocol defines.
	for _, state := range []string{
		protocol.SessionStateRunning,
		protocol.SessionStateWaitingInput,
		protocol.SessionStateIdle,
		protocol.SessionStateUnknown,
	} {
		if state == stateNoSessions {
			t.Fatalf("placeholder leaked into the session state vocabulary as %q", state)
		}
	}
}

// TestListRowsPlaceholderUsesTheNamedValue proves the producer and the colour
// mapping share one spelling. A literal in ListRows would let the row text change
// without the colour following it, and the row would silently fall back to the
// default yellow.
func TestListRowsPlaceholderUsesTheNamedValue(t *testing.T) {
	endpoints := []protocol.Endpoint{{EndpointID: "e1", ConnectionState: "online"}, {EndpointID: "e2", ConnectionState: "online"}}
	reports := map[string]protocol.InventoryReport{
		"e1": {CollectionStatus: protocol.CollectionSucceeded},
	}
	rows := ListRows(endpoints, reports, "")
	if len(rows) != 2 {
		t.Fatalf("rows = %d, want 2: %#v", len(rows), rows)
	}
	for _, row := range rows {
		if row.State != stateNoSessions {
			t.Fatalf("placeholder state = %q, want %q", row.State, stateNoSessions)
		}
		if got := stateStyle(row.State); got != ansiDim {
			t.Fatalf("placeholder colour = %q, want dim %q", got, ansiDim)
		}
	}
}
