package tui

import (
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

// TestUnverifiedAndUnknownUseDifferentColours proves the two conditions an
// operator must tell apart are not rendered in one colour. An unverified session
// needs a resume decision; a provider-reported unknown session does not. When
// both are plain yellow the row colour carries no such distinction, and the
// operator has to read the summary subset label to learn it.
func TestUnverifiedAndUnknownUseDifferentColours(t *testing.T) {
	unknownStyle := stateStyle("unknown")
	unverifiedStyle := stateStyle("unverified")
	if unknownStyle == unverifiedStyle {
		t.Fatalf("unknown and unverified share one colour %q", unknownStyle)
	}
}

// TestUnverifiedColourCollidesWithNoColourInUse proves the new state colour is
// not a reuse of a colour that already means something else. A state that looked
// like a header, a prompt, a separator or an operator payload would read as
// chrome or as foreign text rather than as a session condition.
//
// The existing state colours are included because a second meaning for one
// colour is the same defect one level down: an operator who learned "green means
// running" must not meet green meaning something else.
func TestUnverifiedColourCollidesWithNoColourInUse(t *testing.T) {
	unverifiedStyle := stateStyle("unverified")
	inUse := map[string]string{
		"header":           ansiBoldCyan,
		"startup text":     ansiCyan,
		"prompt":           ansiBoldGreen,
		"running":          ansiGreen,
		"terminal state":   ansiDim,
		"unknown":          ansiYellow,
		"failed":           ansiRed,
		"operator payload": ansiMagenta,
		"reset":            ansiReset,
	}
	for meaning, style := range inUse {
		if unverifiedStyle == style {
			t.Fatalf("unverified reuses the %s colour %q", meaning, style)
		}
	}
}

// TestUnverifiedRowIsColouredApartFromUnknownRow proves the distinction reaches
// the rendered table, not only the mapping. It also proves the SESSION_STATUS
// cell still shows the reported state, because "unverified" is a colour key and
// never a state: the state vocabulary is a protocol contract.
func TestUnverifiedRowIsColouredApartFromUnknownRow(t *testing.T) {
	rows := []SessionRow{
		{
			EndpointID:        "endpoint-1",
			AdapterID:         "adapter",
			ProviderSessionID: "provider-1",
			DisplayName:       "provider reported",
			State:             protocol.SessionStateUnknown,
			CollectionStatus:  protocol.CollectionSucceeded,
		},
		{
			EndpointID:        "endpoint-1",
			AdapterID:         "adapter",
			ProviderSessionID: "provider-2",
			DisplayName:       "liveness not verified",
			State:             protocol.SessionStateUnknown,
			Unverified:        true,
			CollectionStatus:  protocol.CollectionSucceeded,
		},
	}
	var colored, errors strings.Builder
	if err := RenderTable(&colored, &errors, rows, nil, TableOptions{Color: ColorPolicy{Enabled: true}}); err != nil {
		t.Fatal(err)
	}
	rendered := colored.String()
	if !strings.Contains(rendered, ansiBoldYellow) {
		t.Fatalf("unverified row must use its own colour, got %q", rendered)
	}
	// The plain layout keeps SESSION_STATUS, so the reported state stays visible
	// and the colour key never leaks into the text. The summary line legitimately
	// names the subset, so only the table body is checked here.
	var plain strings.Builder
	if err := RenderTable(&plain, &errors, rows, nil, TableOptions{}); err != nil {
		t.Fatal(err)
	}
	body := plain.String()
	if index := strings.LastIndex(body, "\nunknown("); index >= 0 {
		body = body[:index]
	}
	if strings.Contains(body, "unverified") {
		t.Fatalf("colour key must not appear as a state value, got %q", body)
	}
	if got := strings.Count(body, protocol.SessionStateUnknown); got != 2 {
		t.Fatalf("both rows must report the unknown state, got %d occurrences in %q", got, body)
	}
}

// TestUnverifiedSummaryLabelUsesTheUnverifiedColour proves the summary subset
// label is coloured like the rows it counts, so the label and the rows it names
// read as one condition instead of two.
func TestUnverifiedSummaryLabelUsesTheUnverifiedColour(t *testing.T) {
	rows := []SessionRow{
		{SessionID: "a", State: "unknown", Unverified: true},
		{SessionID: "b", State: "unknown"},
	}
	var out strings.Builder
	if err := writeStatusSummary(&out, rows, ColorPolicy{Enabled: true}); err != nil {
		t.Fatal(err)
	}
	summary := out.String()
	if !strings.Contains(summary, ansiBoldYellow+"unverified(1)"+ansiReset) {
		t.Fatalf("unverified label must use the unverified colour, got %q", summary)
	}
	if !strings.Contains(summary, ansiYellow+"unknown(2)"+ansiReset) {
		t.Fatalf("unknown bucket must keep the unknown colour, got %q", summary)
	}
}
