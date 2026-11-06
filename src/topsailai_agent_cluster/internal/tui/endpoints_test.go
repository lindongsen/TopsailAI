package tui

import (
	"context"
	"encoding/json"
	"io"
	"reflect"
	"strings"
	"testing"
	"time"

	"topsailai_agent_cluster/internal/protocol"
)

// endpointFixture returns one endpoint per connection state plus one endpoint with
// no reported details, so missing values and every colour branch are covered.
func endpointFixture() []protocol.Endpoint {
	return []protocol.Endpoint{
		{EndpointID: "endpoint-2", Hostname: "host-2", DisplayName: "Second", ConnectionState: "offline", ObservedAtMS: 1700000000000, CapabilityRevision: "cap-2"},
		{EndpointID: "endpoint-1", Hostname: "host-1", DisplayName: "First", ConnectionState: "online", ObservedAtMS: 1700000000000, CapabilityRevision: "cap-1"},
		{EndpointID: "endpoint-3", ConnectionState: "suspect"},
	}
}

// endpointRow returns the rendered line of one endpoint, so a per-row assertion
// cannot accidentally match another row.
func endpointRow(t *testing.T, text, endpointID string) string {
	t.Helper()
	for _, line := range strings.Split(text, "\n") {
		if strings.Contains(line, endpointID) {
			return line
		}
	}
	t.Fatalf("rendered endpoints missing row %q: %q", endpointID, text)
	return ""
}

// TestRenderEndpointsTableFramingAndMissingValues pins the framed layout, the
// stable ID ordering and the "-" placeholder for unreported values.
func TestRenderEndpointsTableFramingAndMissingValues(t *testing.T) {
	var out strings.Builder
	if err := RenderEndpoints(&out, endpointFixture(), "", false, TableOptions{Location: time.UTC}); err != nil {
		t.Fatal(err)
	}
	text := out.String()
	for _, header := range columnHeaders(endpointColumns) {
		if !strings.Contains(text, header) {
			t.Fatalf("endpoints table missing header %q: %q", header, text)
		}
	}
	if !strings.Contains(text, "─┼─") {
		t.Fatalf("endpoints table missing separators: %q", text)
	}
	if strings.Contains(text, "\x1b") {
		t.Fatalf("plain endpoints table contains ANSI bytes: %q", text)
	}
	// The Server returns endpoints in map order, so the table must sort by ID.
	first := strings.Index(text, "endpoint-1")
	second := strings.Index(text, "endpoint-2")
	third := strings.Index(text, "endpoint-3")
	if first < 0 || second < 0 || third < 0 || !(first < second && second < third) {
		t.Fatalf("endpoints are not sorted by ID: %q", text)
	}
	// endpoint-3 reports no hostname, display name, observation time or revision,
	// so four cells must show the dash placeholder.
	unreported := endpointRow(t, text, "endpoint-3")
	if !strings.Contains(unreported, "suspect") || strings.Count(unreported, "-") != 5 {
		t.Fatalf("unreported endpoint values are not rendered as dashes: %q", unreported)
	}
	if !strings.Contains(text, "22:13:20") {
		t.Fatalf("reported observation time is not formatted: %q", text)
	}
}

// TestRenderEndpointsFilterAndEmptyResult pins the optional ID filter and the
// explicit empty result, so an unknown filter is not a silent full listing.
func TestRenderEndpointsFilterAndEmptyResult(t *testing.T) {
	var filtered strings.Builder
	if err := RenderEndpoints(&filtered, endpointFixture(), "endpoint-2", false, TableOptions{Location: time.UTC}); err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(filtered.String(), "endpoint-2") || strings.Contains(filtered.String(), "endpoint-1") || strings.Contains(filtered.String(), "endpoint-3") {
		t.Fatalf("filter did not isolate one endpoint: %q", filtered.String())
	}
	if !strings.Contains(filtered.String(), "offline(1)") {
		t.Fatalf("filtered summary does not count only the selected endpoint: %q", filtered.String())
	}

	var unknown strings.Builder
	if err := RenderEndpoints(&unknown, endpointFixture(), "endpoint-missing", false, TableOptions{}); err != nil {
		t.Fatal(err)
	}
	// An empty result keeps the framed header, exactly like the session list, and
	// states the emptiness explicitly instead of rendering nothing.
	if text := unknown.String(); !strings.HasSuffix(text, "no endpoints\n") || !strings.Contains(text, "ENDPOINT_ID") {
		t.Fatalf("unknown filter output=%q", text)
	}

	var empty strings.Builder
	if err := RenderEndpoints(&empty, nil, "", false, TableOptions{}); err != nil {
		t.Fatal(err)
	}
	if text := empty.String(); !strings.HasSuffix(text, "no endpoints\n") || strings.Contains(text, "endpoint-") {
		t.Fatalf("empty inventory output=%q", text)
	}
}

// TestRenderEndpointsJSONKeepsEveryReportedField pins the JSON projection, which
// must carry the reported fields without presentation bytes.
func TestRenderEndpointsJSONKeepsEveryReportedField(t *testing.T) {
	var out strings.Builder
	if err := RenderEndpoints(&out, endpointFixture(), "", true, TableOptions{Color: ColorPolicy{Enabled: true}}); err != nil {
		t.Fatal(err)
	}
	text := out.String()
	if strings.Contains(text, "ENDPOINT_ID") || strings.Contains(text, "\x1b") {
		t.Fatalf("JSON endpoints contain presentation bytes: %q", text)
	}
	var decoded []protocol.Endpoint
	if err := json.Unmarshal([]byte(text), &decoded); err != nil {
		t.Fatalf("JSON endpoints=%q err=%v", text, err)
	}
	if len(decoded) != 3 {
		t.Fatalf("JSON endpoints=%q count=%d want 3", text, len(decoded))
	}
	if decoded[0].EndpointID != "endpoint-1" || decoded[0].Hostname != "host-1" || decoded[0].DisplayName != "First" ||
		decoded[0].ConnectionState != "online" || decoded[0].ObservedAtMS != 1700000000000 || decoded[0].CapabilityRevision != "cap-1" {
		t.Fatalf("JSON endpoint lost reported fields: %#v", decoded[0])
	}
}

// TestRenderEndpointsConnectionStateColourAndSummary pins the connection-state
// colour mapping and the summary counts, which are a different domain from the
// session state mapping.
func TestRenderEndpointsConnectionStateColourAndSummary(t *testing.T) {
	var out strings.Builder
	if err := RenderEndpoints(&out, endpointFixture(), "", false, TableOptions{Color: ColorPolicy{Enabled: true}, Location: time.UTC}); err != nil {
		t.Fatal(err)
	}
	text := out.String()
	for _, want := range []string{ansiGreen + "endpoint-1", ansiRed + "endpoint-2", ansiYellow + "endpoint-3"} {
		if !strings.Contains(text, want) {
			t.Fatalf("coloured endpoints missing %q: %q", want, text)
		}
	}
	if !strings.Contains(text, ansiBoldCyan+"ENDPOINT_ID") {
		t.Fatalf("coloured endpoints missing styled header: %q", text)
	}
	// The summary counts every state in a deterministic order.
	lines := strings.Split(strings.TrimRight(text, "\n"), "\n")
	summary := lines[len(lines)-1]
	for _, want := range []string{ansiGreen + "online(1)", ansiYellow + "suspect(1)", ansiRed + "offline(1)"} {
		if !strings.Contains(summary, want) {
			t.Fatalf("summary missing %q: %q", want, summary)
		}
	}
	if !strings.Contains(summary, ansiDim+" | ") {
		t.Fatalf("summary separators are not dimmed: %q", summary)
	}
}

// TestRenderEndpointsNarrowWidthKeepsEveryField pins the narrow layout, so a
// small terminal still shows each endpoint field instead of dropping columns.
func TestRenderEndpointsNarrowWidthKeepsEveryField(t *testing.T) {
	var out strings.Builder
	if err := RenderEndpoints(&out, endpointFixture(), "endpoint-1", false, TableOptions{Width: 20, Location: time.UTC}); err != nil {
		t.Fatal(err)
	}
	text := out.String()
	if strings.Contains(text, "─┼─") {
		t.Fatalf("narrow endpoints kept the wide layout: %q", text)
	}
	for _, header := range columnHeaders(endpointColumns) {
		// The narrow layout clips the label itself, so compare against the clipped
		// form instead of the full header text.
		if label := clipCell(header+": ", 20); !strings.Contains(text, label) {
			t.Fatalf("narrow endpoints missing field %q: %q", label, text)
		}
	}
	if !strings.Contains(text, "host-1") {
		t.Fatalf("narrow endpoints lost the hostname: %q", text)
	}
}

// TestRenderEndpointsEscapesUntrustedValues pins terminal sanitisation, because
// hostnames and display names are provider-reported strings.
func TestRenderEndpointsEscapesUntrustedValues(t *testing.T) {
	endpoints := []protocol.Endpoint{{
		EndpointID:      "endpoint-1",
		Hostname:        "host\nwith\x1b[31mcontrol",
		DisplayName:     `back\slash`,
		ConnectionState: "online",
	}}
	var out strings.Builder
	if err := RenderEndpoints(&out, endpoints, "", false, TableOptions{}); err != nil {
		t.Fatal(err)
	}
	text := out.String()
	if strings.Contains(text, "\x1b") {
		t.Fatalf("escaped endpoints leaked control bytes: %q", text)
	}
	if !strings.Contains(text, "host�with") {
		t.Fatalf("escaped endpoints did not replace the newline: %q", text)
	}
	if !strings.Contains(text, `back\\slash`) {
		t.Fatalf("escaped endpoints did not escape the backslash: %q", text)
	}
}

// TestCommandRunnerEndpointsReadsOnlyTheEndpointProjection pins that listing
// endpoints never forces provider discovery through an inventory read.
func TestCommandRunnerEndpointsReadsOnlyTheEndpointProjection(t *testing.T) {
	api := &runnerStubAPI{endpoints: endpointFixture()}
	var out strings.Builder
	if err := (CommandRunner{API: api, Policy: LegacyPolicy}).Endpoints(context.Background(), &out, "", false, TableOptions{}); err != nil {
		t.Fatal(err)
	}
	if got, want := strings.Join(api.calls, ","), "list"; got != want {
		t.Fatalf("calls=%s want=%s", got, want)
	}
	if !strings.Contains(out.String(), "endpoint-1") {
		t.Fatalf("endpoints output=%q", out.String())
	}
}

// TestInteractiveEndpointsRejectsOptionsAndKeepsRowBindings pins the REPL
// behaviour: options are rejected before any read, and the session row bindings
// used by cd <number> are untouched.
func TestInteractiveEndpointsRejectsOptionsAndKeepsRowBindings(t *testing.T) {
	api := &runnerStubAPI{endpoints: endpointFixture()}
	state := seedUnitCState()
	// endpoints is a workspace-scope command, so the REPL must be in workspace
	// scope for the option rejection and the listing to be reached at all.
	state.Scope = ScopeState{Kind: ScopeWorkspace}
	before := cloneUnitCState(state)

	var out, diagnostics strings.Builder
	if _, err := executeInteractiveLine(context.Background(), api, &state, "endpoints --json", nil, &out, &out, &diagnostics, InteractiveOptions{}); err == nil {
		t.Fatal("interactive endpoints accepted a non-interactive option")
	}
	if out.Len() != 0 || diagnostics.Len() != 0 {
		t.Fatalf("rejected endpoints wrote output=%q diagnostics=%q", out.String(), diagnostics.String())
	}
	if len(api.calls) != 0 {
		t.Fatalf("rejected endpoints still queried the Server: %v", api.calls)
	}

	out.Reset()
	if _, err := executeInteractiveLine(context.Background(), api, &state, "endpoints", nil, &out, &out, &diagnostics, InteractiveOptions{}); err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(out.String(), "endpoint-1") || !strings.Contains(out.String(), "ENDPOINT_ID") {
		t.Fatalf("interactive endpoints output=%q", out.String())
	}
	if !reflect.DeepEqual(state, before) {
		t.Fatalf("interactive endpoints changed the REPL state: %#v want %#v", state, before)
	}
}

// TestInteractiveEndpointsRejectedOutsideWorkspaceScope pins the scope gate, so
// endpoint and session scope keep their existing command sets.
func TestInteractiveEndpointsRejectedOutsideWorkspaceScope(t *testing.T) {
	for _, kind := range []ScopeKind{ScopeEndpoint, ScopeSession} {
		api := &runnerStubAPI{endpoints: endpointFixture()}
		state := seedUnitCState()
		state.Scope.Kind = kind
		var out strings.Builder
		_, err := executeInteractiveLine(context.Background(), api, &state, "endpoints", nil, &out, &out, io.Discard, InteractiveOptions{})
		if err == nil || !strings.Contains(err.Error(), "unavailable in "+kind.String()+" scope") {
			t.Fatalf("%s scope endpoints err=%v", kind, err)
		}
		if out.Len() != 0 || len(api.calls) != 0 {
			t.Fatalf("%s scope endpoints wrote output=%q calls=%v", kind, out.String(), api.calls)
		}
	}
}
