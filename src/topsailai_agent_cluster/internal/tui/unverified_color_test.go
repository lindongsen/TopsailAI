package tui

import (
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

// TestStateColourMapping pins the complete session-state colour mapping, so a
// state cannot silently drift into another colour. The mapping is deliberately
// small: green means running, dim means a state that needs no attention, red
// means a state that needs attention, and yellow is the remaining uncertain
// middle.
//
// idle, unknown and unverified share dim on purpose. They are all states where
// nothing is actively running and nothing has failed, so an operator scanning
// the table should not have to read them. The difference between an unverified
// session and a provider-reported unknown session is carried by the summary
// subset label and by the refusal message, not by the row colour.
func TestStateColourMapping(t *testing.T) {
	cases := []struct {
		state string
		style string
	}{
		{"running", ansiGreen},
		{"stopped", ansiDim},
		{"completed", ansiDim},
		{"idle", ansiDim},
		{"unknown", ansiDim},
		{"unverified", ansiDim},
		{"failed", ansiRed},
		{"error", ansiRed},
		{"offline", ansiRed},
		{"waiting_input", ansiYellow},
		{"ready", ansiYellow},
	}
	for _, testCase := range cases {
		t.Run(testCase.state, func(t *testing.T) {
			if got := stateStyle(testCase.state); got != testCase.style {
				t.Fatalf("state %q colour = %q, want %q", testCase.state, got, testCase.style)
			}
		})
	}
}

// TestOfflineIsRedAndNotYellow proves the offline session state is coloured as a
// condition that needs attention. It used to fall through to the default yellow,
// which read as "uncertain" for a state that is a definite negative.
//
// The endpoint connection state "offline" is a different domain with its own
// mapping in connectionStateStyle, so this test also proves the two mappings are
// not accidentally shared.
func TestOfflineIsRedAndNotYellow(t *testing.T) {
	if got := stateStyle("offline"); got != ansiRed {
		t.Fatalf("offline session state colour = %q, want red %q", got, ansiRed)
	}
	if got := stateStyle("offline"); got == ansiYellow {
		t.Fatalf("offline must not fall through to the default yellow")
	}
	if got := connectionStateStyle("offline"); got != ansiRed {
		t.Fatalf("endpoint connection offline colour = %q, want red %q", got, ansiRed)
	}
}

// TestDimStatesShareOneColour proves the three dim states really are one colour,
// so the intent is recorded rather than inferred from three separate cases. A
// future change that gives one of them its own colour has to change this test,
// which is the point: the sharing is a decision, not an accident.
func TestDimStatesShareOneColour(t *testing.T) {
	for _, state := range []string{"idle", "unknown", "unverified"} {
		if got := stateStyle(state); got != ansiDim {
			t.Fatalf("state %q colour = %q, want dim %q", state, got, ansiDim)
		}
	}
}

// TestUnverifiedRowIsDimAndKeepsTheReportedState proves the distinction reaches
// the rendered table. An unverified session is coloured dim like any other
// unknown state, and the SESSION_STATUS cell still shows the reported "unknown",
// because "unverified" is a colour key and never a state: the state vocabulary is
// a protocol contract.
func TestUnverifiedRowIsDimAndKeepsTheReportedState(t *testing.T) {
	rows := []SessionRow{
		{
			EndpointID:          "endpoint-1",
			AdapterID:           "adapter",
			ProviderSessionID:   "provider-1",
			ProviderDisplayName: "provider reported",
			State:               protocol.SessionStateUnknown,
			CollectionStatus:    protocol.CollectionSucceeded,
		},
		{
			EndpointID:          "endpoint-1",
			AdapterID:           "adapter",
			ProviderSessionID:   "provider-2",
			ProviderDisplayName: "liveness not verified",
			State:               protocol.SessionStateUnknown,
			Unverified:          true,
			CollectionStatus:    protocol.CollectionSucceeded,
		},
	}
	var colored, errors strings.Builder
	if err := RenderTable(&colored, &errors, rows, nil, TableOptions{Color: ColorPolicy{Enabled: true}}); err != nil {
		t.Fatal(err)
	}
	rendered := colored.String()
	if !strings.Contains(rendered, ansiDim) {
		t.Fatalf("unverified row must use the dim colour, got %q", rendered)
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

// TestUnverifiedSummaryLabelIsAbsent proves the summary line never names the
// unverified subset, with colour enabled as well as disabled. The unknown bucket
// keeps its dim colour, because the rows it counts are still dim; only the extra
// label is gone, so the line reports one dimension.
func TestUnverifiedSummaryLabelIsAbsent(t *testing.T) {
	rows := []SessionRow{
		{ClusterSessionID: "a", State: "unknown", Unverified: true},
		{ClusterSessionID: "b", State: "unknown"},
	}
	var out strings.Builder
	if err := writeStatusSummary(&out, rows, ColorPolicy{Enabled: true}); err != nil {
		t.Fatal(err)
	}
	summary := out.String()
	if strings.Contains(summary, "unverified") {
		t.Fatalf("summary must not name the unverified subset, got %q", summary)
	}
	if !strings.Contains(summary, ansiDim+"unknown(2)"+ansiReset) {
		t.Fatalf("unknown bucket must use the dim colour, got %q", summary)
	}
}
