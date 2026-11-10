package tui

import (
	"context"
	"errors"
	"io"
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

// interactiveHistoryStub adds the optional HistoryQuerier seam to the shared
// interactive stub, so one scenario can render history and still reuse the same
// inventory, capability and admission recording as every other REPL test.
type interactiveHistoryStub struct {
	*interactiveStub
	history      map[string]protocol.HistoryResult
	historyEr    map[string]error
	historyCalls []string
	// historyLimits records the caller limit of every interactive read. The REPL
	// always passes zero, so a non-zero value would mean the surface narrowed a
	// table the operator selects rows from.
	historyLimits []int
}

// GetHistory records the queried endpoint so a test can prove which endpoint the
// interactive surface addressed.
func (s *interactiveHistoryStub) GetHistory(_ context.Context, endpointID string, limit int) (protocol.HistoryResult, error) {
	s.historyCalls = append(s.historyCalls, endpointID)
	s.historyLimits = append(s.historyLimits, limit)
	if err := s.historyEr[endpointID]; err != nil {
		return protocol.HistoryResult{}, err
	}
	return s.history[endpointID], nil
}

// historyReport builds a complete report holding the given sessions, so a test
// states only the sessions it cares about.
func historyReport(sessions ...protocol.Session) protocol.InventoryReport {
	return protocol.InventoryReport{
		ReportComplete:   true,
		CollectionStatus: protocol.CollectionSucceeded,
		Sessions:         sessions,
	}
}

// historyScenarioStub serves one endpoint whose inventory holds the given
// sessions. A single endpoint keeps the inventory call sequence predictable, so
// the startup list, the history join and the resume revalidation each observe the
// call the test expects.
func historyScenarioStub(rows []protocol.HistoryRow, report protocol.InventoryReport) *interactiveHistoryStub {
	return &interactiveHistoryStub{
		interactiveStub: &interactiveStub{
			endpoints: []protocol.Endpoint{{EndpointID: "endpoint-1", Hostname: "host-one"}},
			reports:   map[string]protocol.InventoryReport{"endpoint-1": report},
		},
		history: map[string]protocol.HistoryResult{"endpoint-1": {Rows: rows}},
	}
}

// TestInteractiveHistoryRendersTableAndBindsRowNumbers proves the interactive
// surface renders the history layout and queries exactly the named endpoint.
//
// The rows carry a distinguishing display name because the interactive table
// hides SESSION_ID, so the provider session ID can no longer be used as the
// marker that proves both rows were rendered.
func TestInteractiveHistoryRendersTableAndBindsRowNumbers(t *testing.T) {
	stub := historyScenarioStub([]protocol.HistoryRow{
		{ProviderSessionID: "wa-live", DisplayName: "live work", Resumable: false, ResumeBlockedReason: protocol.ResumeBlockedProviderRunning},
		{ProviderSessionID: "wa-past", DisplayName: "past work", Resumable: true, ResourceID: "res-past"},
	}, historyReport(historyLiveSession("res-live", "wa-live", "gen-1")))

	output, diagnostics := runScope(t, stub, "history endpoint-1\nexit\n", ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	for _, want := range []string{"PROVIDER_STATUS", "LIVE", "RESUMABLE", "live work", "past work"} {
		if !strings.Contains(output, want) {
			t.Fatalf("history table missing %q: %q", want, output)
		}
	}
	// The interactive history table hides SESSION_ID, so neither the header nor
	// the provider session ID cell may be printed.
	if strings.Contains(output, "SESSION_ID") {
		t.Fatalf("interactive history table still prints the SESSION_ID header: %q", output)
	}
	if strings.Contains(output, "wa-live") || strings.Contains(output, "wa-past") {
		t.Fatalf("interactive history table still prints a provider session ID cell: %q", output)
	}
	if len(stub.historyCalls) != 1 || stub.historyCalls[0] != "endpoint-1" {
		t.Fatalf("history calls=%v", stub.historyCalls)
	}
}

// TestInteractiveHistoryEndpointScopeUsesCurrentEndpoint proves endpoint scope
// needs no argument, because the operator is already inside one machine.
func TestInteractiveHistoryEndpointScopeUsesCurrentEndpoint(t *testing.T) {
	stub := historyScenarioStub([]protocol.HistoryRow{{ProviderSessionID: "wa-past", Resumable: true}}, historyReport())

	output, diagnostics := runScope(t, stub, "cd host-one/endpoint-1\nhistory\nexit\n", ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if !strings.Contains(output, "PROVIDER_STATUS") {
		t.Fatalf("history table not rendered: %q", output)
	}
	if len(stub.historyCalls) != 1 || stub.historyCalls[0] != "endpoint-1" {
		t.Fatalf("history calls=%v", stub.historyCalls)
	}
}

// TestInteractiveHistoryEndpointScopeRejectsDifferentEndpoint proves a number or
// name from another machine is never silently retargeted.
func TestInteractiveHistoryEndpointScopeRejectsDifferentEndpoint(t *testing.T) {
	stub := historyScenarioStub([]protocol.HistoryRow{{ProviderSessionID: "wa-past"}}, historyReport())

	_, diagnostics := runScope(t, stub, "cd host-one/endpoint-1\nhistory endpoint-2\nexit\n", ColorPolicy{})
	want := `error: history "endpoint-2" does not match the current endpoint "endpoint-1"; run cd .. to query another endpoint`
	if !strings.Contains(diagnostics, want) {
		t.Fatalf("diagnostics=%q, want %q", diagnostics, want)
	}
	if len(stub.historyCalls) != 0 {
		t.Fatalf("rejected history reached the API: %v", stub.historyCalls)
	}
}

// TestInteractiveHistoryWorkspaceScopeRequiresEndpoint proves workspace scope has
// no current endpoint, so the argument is mandatory.
func TestInteractiveHistoryWorkspaceScopeRequiresEndpoint(t *testing.T) {
	stub := historyScenarioStub([]protocol.HistoryRow{{ProviderSessionID: "wa-past"}}, historyReport())

	_, diagnostics := runScope(t, stub, "history\nexit\n", ColorPolicy{})
	if !strings.Contains(diagnostics, "error: invalid arguments") {
		t.Fatalf("diagnostics=%q", diagnostics)
	}
	if !strings.Contains(diagnostics, "usage: history <endpoint-id-or-hostname>") {
		t.Fatalf("diagnostics=%q", diagnostics)
	}
	if len(stub.historyCalls) != 0 {
		t.Fatalf("argument-less history reached the API: %v", stub.historyCalls)
	}
}

// TestInteractiveHistoryRejectsJSONOption proves the interactive surface refuses
// a non-interactive option instead of ignoring it.
func TestInteractiveHistoryRejectsJSONOption(t *testing.T) {
	stub := historyScenarioStub([]protocol.HistoryRow{{ProviderSessionID: "wa-past"}}, historyReport())

	_, diagnostics := runScope(t, stub, "history endpoint-1 --json\nexit\n", ColorPolicy{})
	if !strings.Contains(diagnostics, `option "--json" is available only in non-interactive mode`) {
		t.Fatalf("diagnostics=%q", diagnostics)
	}
	if len(stub.historyCalls) != 0 {
		t.Fatalf("rejected option reached the API: %v", stub.historyCalls)
	}
}

// TestInteractiveHistoryReportsMissingSeam proves a client without the history
// seam reports the missing capability instead of rendering an empty table.
func TestInteractiveHistoryReportsMissingSeam(t *testing.T) {
	api := &historylessAPI{endpoints: []protocol.Endpoint{{EndpointID: "endpoint-1"}}}

	_, diagnostics := runScope(t, api, "history endpoint-1\nexit\n", ColorPolicy{})
	want := "history is unavailable: this client cannot query provider history"
	if !strings.Contains(diagnostics, want) {
		t.Fatalf("diagnostics=%q, want %q", diagnostics, want)
	}
}

// TestInteractiveHistorySurfacesProviderErrorCode proves a provider error code is
// reported with the endpoint it belongs to.
func TestInteractiveHistorySurfacesProviderErrorCode(t *testing.T) {
	stub := historyScenarioStub(nil, historyReport())
	stub.history["endpoint-1"] = protocol.HistoryResult{ErrorCode: protocol.HistoryUnsupported}

	_, diagnostics := runScope(t, stub, "history endpoint-1\nexit\n", ColorPolicy{})
	want := `history for endpoint "endpoint-1" failed: history_unsupported`
	if !strings.Contains(diagnostics, want) {
		t.Fatalf("diagnostics=%q, want %q", diagnostics, want)
	}
}

// TestInteractiveHistoryLabelsTruncatedWindow proves a bounded provider window is
// never presented as a complete history.
func TestInteractiveHistoryLabelsTruncatedWindow(t *testing.T) {
	stub := historyScenarioStub(nil, historyReport())
	stub.history["endpoint-1"] = protocol.HistoryResult{
		Rows:      []protocol.HistoryRow{{ProviderSessionID: "wa-past"}},
		Truncated: true,
	}

	_, diagnostics := runScope(t, stub, "history endpoint-1\nexit\n", ColorPolicy{})
	if !strings.Contains(diagnostics, "bounded provider window") {
		t.Fatalf("diagnostics=%q", diagnostics)
	}
}

// TestInteractiveHistoryReportsUnjoinedInventory proves an unavailable inventory
// leaves rows unjoined rather than assuming they are stopped.
func TestInteractiveHistoryReportsUnjoinedInventory(t *testing.T) {
	stub := historyScenarioStub([]protocol.HistoryRow{{ProviderSessionID: "wa-past"}}, historyReport())
	stub.interactiveStub.inventoryErr = errors.New("inventory unavailable")

	output, diagnostics := runScope(t, stub, "history endpoint-1\nexit\n", ColorPolicy{})
	if !strings.Contains(diagnostics, "history rows are unjoined") {
		t.Fatalf("diagnostics=%q", diagnostics)
	}
	if !strings.Contains(output, "unjoined") {
		t.Fatalf("table must label unjoined rows: %q", output)
	}
}

// TestInteractiveHistoryCDEntersLiveRow proves a live history row is entered
// through the joined pair rather than through the provider key.
func TestInteractiveHistoryCDEntersLiveRow(t *testing.T) {
	stub := historyScenarioStub(
		[]protocol.HistoryRow{{ProviderSessionID: "wa-live", Resumable: false, ResumeBlockedReason: protocol.ResumeBlockedProviderRunning}},
		historyReport(historyLiveSession("res-live", "wa-live", "gen-1")),
	)

	output, diagnostics := runScope(t, stub, "history endpoint-1\ncd 1\nexit\n", ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if got := lastPrompt(output); got != "session[host-one/wa-live]>" {
		t.Fatalf("prompt=%q, want session scope", got)
	}
}

// TestInteractiveHistoryCDRejectsNonLiveRow proves a past row cannot be entered
// and the failure names the resume remedy.
func TestInteractiveHistoryCDRejectsNonLiveRow(t *testing.T) {
	stub := historyScenarioStub(
		[]protocol.HistoryRow{{ProviderSessionID: "wa-past", Resumable: true, ResourceID: "res-past"}},
		historyReport(),
	)

	_, diagnostics := runScope(t, stub, "history endpoint-1\ncd 1\nexit\n", ColorPolicy{})
	want := `history row 1 is not live on endpoint "endpoint-1", so it cannot be entered; use resume 1 to resume it`
	if !strings.Contains(diagnostics, want) {
		t.Fatalf("diagnostics=%q, want %q", diagnostics, want)
	}
}

// TestInteractiveHistoryCDRejectsOutOfRangeRow proves the history namespace
// reports its own valid range instead of the live list range.
func TestInteractiveHistoryCDRejectsOutOfRangeRow(t *testing.T) {
	stub := historyScenarioStub(
		[]protocol.HistoryRow{{ProviderSessionID: "wa-past", Resumable: true}},
		historyReport(),
	)

	_, diagnostics := runScope(t, stub, "history endpoint-1\ncd 99\nexit\n", ColorPolicy{})
	if !strings.Contains(diagnostics, "row 99 is out of range; valid history rows are 1-1") {
		t.Fatalf("diagnostics=%q", diagnostics)
	}
}

// TestCDHistoryRowNumberWithoutNamespaceExplainsTheFix proves the helper refuses
// row navigation before any history render. The startup list always populates the
// live namespace, so only a direct call can reach this branch.
func TestCDHistoryRowNumberWithoutNamespaceExplainsTheFix(t *testing.T) {
	stub := historyScenarioStub(nil, historyReport())
	state := &interactiveState{}

	err := cdHistoryRowNumber(state, stub, context.Background(), 1)
	if err == nil || !strings.Contains(err.Error(), "no history table is available for row navigation; run history first") {
		t.Fatalf("err=%v", err)
	}
}

// TestInteractiveListRestoresLiveNamespaceAfterHistory proves a list render
// reclaims the row numbers, so a history number never survives into a list.
func TestInteractiveListRestoresLiveNamespaceAfterHistory(t *testing.T) {
	stub := historyScenarioStub(
		[]protocol.HistoryRow{{ProviderSessionID: "wa-past", Resumable: true, ResourceID: "res-past"}},
		historyReport(historyLiveSession("res-live", "wa-live", "gen-1")),
	)

	output, diagnostics := runScope(t, stub, "history endpoint-1\nlist\ncd 1\nexit\n", ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if got := lastPrompt(output); got != "session[host-one/wa-live]>" {
		t.Fatalf("prompt=%q, want the list row rather than the history row", got)
	}
}

// TestInteractiveResumeSubmitsAgentResumeWithoutGeneration proves resume addresses
// the opaque handle and carries no generation, because it authorizes on absence.
func TestInteractiveResumeSubmitsAgentResumeWithoutGeneration(t *testing.T) {
	stub := historyScenarioStub(
		[]protocol.HistoryRow{{ProviderSessionID: "wa-past", Resumable: true, ResourceID: "res-past"}},
		historyReport(),
	)

	output, diagnostics := runScope(t, stub, "history endpoint-1\nresume 1\ny\nexit\n", ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if stub.admit != 1 {
		t.Fatalf("admitted=%d", stub.admit)
	}
	intent := stub.intents[0]
	if intent.Operation != protocol.OperationAgentResume || intent.EndpointID != "endpoint-1" {
		t.Fatalf("wrong resume intent: %+v", intent)
	}
	if intent.Target == nil || intent.Target.ResourceID != "res-past" || intent.Target.Generation != "" {
		t.Fatalf("wrong resume target: %+v", intent.Target)
	}
	if !strings.Contains(output, "history row numbers are stale after resume; run history to refresh") {
		t.Fatalf("missing row invalidation notice: %q", output)
	}
}

// TestInteractiveResumeRejectsLiveRow proves a running session is entered rather
// than resumed.
func TestInteractiveResumeRejectsLiveRow(t *testing.T) {
	stub := historyScenarioStub(
		[]protocol.HistoryRow{{ProviderSessionID: "wa-live", Resumable: false, ResumeBlockedReason: protocol.ResumeBlockedProviderRunning}},
		historyReport(historyLiveSession("res-live", "wa-live", "gen-1")),
	)

	_, diagnostics := runScope(t, stub, "history endpoint-1\nresume 1\nexit\n", ColorPolicy{})
	want := `history row 1 is live on endpoint "endpoint-1", so it cannot be resumed; use cd 1 to enter it`
	if !strings.Contains(diagnostics, want) {
		t.Fatalf("diagnostics=%q, want %q", diagnostics, want)
	}
	if stub.admit != 0 {
		t.Fatalf("live row admitted %d commands", stub.admit)
	}
}

// TestInteractiveResumeReportsAdapterReason proves the adapter verdict is
// reported verbatim instead of being re-derived by the cluster.
func TestInteractiveResumeReportsAdapterReason(t *testing.T) {
	stub := historyScenarioStub(
		[]protocol.HistoryRow{{ProviderSessionID: "wa-past", Resumable: false, ResumeBlockedReason: protocol.ResumeBlockedWorkspaceMissing}},
		historyReport(),
	)

	_, diagnostics := runScope(t, stub, "history endpoint-1\nresume 1\nexit\n", ColorPolicy{})
	if !strings.Contains(diagnostics, "history row 1 is not resumable: workspace_missing") {
		t.Fatalf("diagnostics=%q", diagnostics)
	}
	if stub.admit != 0 {
		t.Fatalf("non-resumable row admitted %d commands", stub.admit)
	}
}

// TestInteractiveResumeRejectsMissingResourceHandle proves a row without the
// opaque handle cannot be addressed at all.
func TestInteractiveResumeRejectsMissingResourceHandle(t *testing.T) {
	stub := historyScenarioStub(
		[]protocol.HistoryRow{{ProviderSessionID: "wa-past", Resumable: true}},
		historyReport(),
	)

	_, diagnostics := runScope(t, stub, "history endpoint-1\nresume 1\nexit\n", ColorPolicy{})
	if !strings.Contains(diagnostics, "history row 1 has no resource handle, so it cannot be resumed; run history again") {
		t.Fatalf("diagnostics=%q", diagnostics)
	}
	if stub.admit != 0 {
		t.Fatalf("handle-less row admitted %d commands", stub.admit)
	}
}

// TestInteractiveResumeRejectsNonNumericArgument proves resume accepts a row
// number only, so a provider key is never mistaken for a selection.
func TestInteractiveResumeRejectsNonNumericArgument(t *testing.T) {
	stub := historyScenarioStub(
		[]protocol.HistoryRow{{ProviderSessionID: "wa-past", Resumable: true, ResourceID: "res-past"}},
		historyReport(),
	)

	_, diagnostics := runScope(t, stub, "history endpoint-1\nresume abc\nexit\n", ColorPolicy{})
	if !strings.Contains(diagnostics, "resume accepts a row number only; run list or history to see the rows") {
		t.Fatalf("diagnostics=%q", diagnostics)
	}
	if stub.admit != 0 {
		t.Fatalf("non-numeric argument admitted %d commands", stub.admit)
	}
}

// TestInteractiveResumeBareWithoutUnknownSessionExplainsTheFix proves a bare
// resume is rejected when no listed session is unknown, because there is no
// unambiguous target to recover.
func TestInteractiveResumeBareWithoutUnknownSessionExplainsTheFix(t *testing.T) {
	stub := historyScenarioStub(nil, historyReport())

	_, diagnostics := runScope(t, stub, "list\nresume\nexit\n", ColorPolicy{})
	if !strings.Contains(diagnostics, "no unknown session is listed, so a bare resume has no target; run list and resume <row>") {
		t.Fatalf("diagnostics=%q", diagnostics)
	}
	if stub.admit != 0 {
		t.Fatalf("bare resume without an unknown session admitted %d commands", stub.admit)
	}
}

// TestInteractiveResumeRevalidatesAbsenceBeforeSubmission proves a stale history
// row cannot resume a session that has since started. The inventory reports the
// session live only on the revalidation read, so the history render still shows a
// past row and the guard is the only thing that stops the admission.
func TestInteractiveResumeRevalidatesAbsenceBeforeSubmission(t *testing.T) {
	stub := historyScenarioStub(
		[]protocol.HistoryRow{{ProviderSessionID: "wa-past", Resumable: true, ResourceID: "res-past"}},
		historyReport(historyLiveSession("res-live", "wa-past", "gen-1")),
	)
	// Call 1 is the startup list, call 2 the history join, call 3 the revalidation.
	stub.interactiveStub.sessionPresenceSequence = []bool{true, false, true}

	_, diagnostics := runScope(t, stub, "history endpoint-1\nresume 1\ny\nexit\n", ColorPolicy{})
	want := `session (wa-past) is live on endpoint "endpoint-1", so it cannot be resumed; use cd to enter it`
	if !strings.Contains(diagnostics, want) {
		t.Fatalf("diagnostics=%q, want %q", diagnostics, want)
	}
	if stub.admit != 0 {
		t.Fatalf("stale row admitted %d commands", stub.admit)
	}
}

// TestInteractiveResumeRejectsIncompleteInventory proves an incomplete report
// cannot prove absence, so the resume fails closed instead of guessing.
func TestInteractiveResumeRejectsIncompleteInventory(t *testing.T) {
	stub := historyScenarioStub(
		[]protocol.HistoryRow{{ProviderSessionID: "wa-past", Resumable: true, ResourceID: "res-past"}},
		protocol.InventoryReport{ReportComplete: false, CollectionStatus: protocol.CollectionSucceeded},
	)

	_, diagnostics := runScope(t, stub, "history endpoint-1\nresume 1\ny\nexit\n", ColorPolicy{})
	if !strings.Contains(diagnostics, "cannot be proven") {
		t.Fatalf("diagnostics=%q", diagnostics)
	}
	if stub.admit != 0 {
		t.Fatalf("incomplete inventory admitted %d commands", stub.admit)
	}
}

// TestInteractiveResumeRejectsOfflineEndpoint proves retained inventory from a
// disconnected endpoint never authorizes a resume.
func TestInteractiveResumeRejectsOfflineEndpoint(t *testing.T) {
	stub := historyScenarioStub(
		[]protocol.HistoryRow{{ProviderSessionID: "wa-past", Resumable: true, ResourceID: "res-past"}},
		historyReport(),
	)
	stub.interactiveStub.endpoints[0].ConnectionState = "offline"

	_, diagnostics := runScope(t, stub, "history endpoint-1\nresume 1\ny\nexit\n", ColorPolicy{})
	if !strings.Contains(diagnostics, `endpoint "endpoint-1" is not online: connection_state=offline`) {
		t.Fatalf("diagnostics=%q", diagnostics)
	}
	if stub.admit != 0 {
		t.Fatalf("offline endpoint admitted %d commands", stub.admit)
	}
}

// TestInteractiveResumeWithoutRenderedTableExplainsTheFix proves resume refuses
// to act before any table render, because it has no row to address.
func TestInteractiveResumeWithoutRenderedTableExplainsTheFix(t *testing.T) {
	stub := historyScenarioStub(nil, historyReport())
	state := &interactiveState{}

	err := interactiveResume(context.Background(), stub, state, "1", nil, io.Discard, io.Discard, InteractiveOptions{})
	if err == nil || !strings.Contains(err.Error(), "resume requires a rendered table; run list or history first") {
		t.Fatalf("err=%v", err)
	}
	if stub.admit != 0 {
		t.Fatalf("table-less resume admitted %d commands", stub.admit)
	}
}

// TestInteractiveHistoryRowNumberRejectedInSessionScope proves a bare number in
// session scope reports the scope error instead of resolving against the history
// table. The call is direct because the guard itself is under test: a dispatch
// layer that happens to reject the number first would hide a missing guard.
func TestInteractiveHistoryRowNumberRejectedInSessionScope(t *testing.T) {
	stub := historyScenarioStub(
		[]protocol.HistoryRow{
			{ProviderSessionID: "wa-live", Resumable: false, ResumeBlockedReason: protocol.ResumeBlockedProviderRunning},
			{ProviderSessionID: "wa-past", Resumable: true, ResourceID: "res-past"},
		},
		historyReport(historyLiveSession("res-live", "wa-live", "gen-1")),
	)
	state := &interactiveState{}
	state.Scope = ScopeState{Kind: ScopeSession, EndpointID: "endpoint-1", SessionID: "res-live", Generation: "gen-1"}
	state.history = &historyNamespace{
		EndpointID: "endpoint-1",
		Rows:       map[int]HistoryViewRow{1: {No: 1, EndpointID: "endpoint-1", ProviderSessionID: "wa-live", Joined: true, Live: true, ResourceID: "res-live", Generation: "gen-1"}},
	}

	err := cdHistoryRowNumber(state, stub, context.Background(), 1)
	want := "row-number navigation is unavailable in session scope; use cd .. or cd <session>"
	if err == nil || !strings.Contains(err.Error(), want) {
		t.Fatalf("err=%v, want %q", err, want)
	}
	if state.Scope.Kind != ScopeSession {
		t.Fatalf("scope=%v, want the session scope to be unchanged", state.Scope.Kind)
	}
}

// TestInteractiveHistoryNamespaceClearedAfterEnteringSession proves the history
// row numbers do not survive the transition into a session, so a later number can
// never address a table the operator can no longer see.
func TestInteractiveHistoryNamespaceClearedAfterEnteringSession(t *testing.T) {
	stub := historyScenarioStub(
		[]protocol.HistoryRow{
			{ProviderSessionID: "wa-live", Resumable: false, ResumeBlockedReason: protocol.ResumeBlockedProviderRunning},
			{ProviderSessionID: "wa-past", Resumable: true, ResourceID: "res-past"},
		},
		historyReport(historyLiveSession("res-live", "wa-live", "gen-1")),
	)
	state := &interactiveState{}
	state.history = &historyNamespace{
		EndpointID: "endpoint-1",
		Rows:       map[int]HistoryViewRow{1: {No: 1, EndpointID: "endpoint-1", ProviderSessionID: "wa-live", Joined: true, Live: true, ResourceID: "res-live", Generation: "gen-1"}},
	}

	if err := cdHistoryRowNumber(state, stub, context.Background(), 1); err != nil {
		t.Fatalf("cdHistoryRowNumber: %v", err)
	}
	if state.Scope.Kind != ScopeSession {
		t.Fatalf("scope=%v, want session scope", state.Scope.Kind)
	}
	if state.history != nil {
		t.Fatalf("history namespace survived the session transition: %#v", state.history)
	}
}

// TestInteractiveHistoryCDRejectsAmbiguousRow proves an ambiguous row is refused
// with the real cause. The inventory answered, so telling the operator to refresh
// would send them to a remedy that cannot disambiguate the data.
func TestInteractiveHistoryCDRejectsAmbiguousRow(t *testing.T) {
	stub := historyScenarioStub(nil, historyReport())
	state := &interactiveState{}
	state.history = &historyNamespace{
		EndpointID: "endpoint-1",
		Rows:       map[int]HistoryViewRow{1: {No: 1, EndpointID: "endpoint-1", ProviderSessionID: "wa-dup", Ambiguous: true}},
	}

	err := cdHistoryRowNumber(state, stub, context.Background(), 1)
	if err == nil {
		t.Fatal("an ambiguous row must not be entered")
	}
	if !strings.Contains(err.Error(), "is ambiguous") {
		t.Fatalf("err=%v, want an ambiguity error", err)
	}
	if strings.Contains(err.Error(), "refresh") {
		t.Fatalf("err=%v, must not offer a refresh that cannot disambiguate", err)
	}
	if state.Scope.Kind == ScopeSession {
		t.Fatalf("scope=%v, an ambiguous row must not be entered", state.Scope.Kind)
	}
}

// TestInteractiveResumeRejectsAmbiguousRow proves an ambiguous row is never
// resumed. The inventory reported live sessions for the same provider session ID,
// so resuming would start a second runtime for a session that is already running.
func TestInteractiveResumeRejectsAmbiguousRow(t *testing.T) {
	stub := historyScenarioStub(nil, historyReport())
	state := &interactiveState{}
	state.history = &historyNamespace{
		EndpointID: "endpoint-1",
		Rows: map[int]HistoryViewRow{1: {
			No:                1,
			EndpointID:        "endpoint-1",
			ProviderSessionID: "wa-dup",
			Ambiguous:         true,
			Resumable:         true,
			ResumeResourceID:  "res-dup",
		}},
	}

	// A closed channel makes the confirmation path return immediately, so the test
	// observes the guard under test instead of blocking on an interactive prompt.
	lines := make(chan lineReadResult)
	close(lines)
	err := interactiveResume(context.Background(), stub, state, "1", lines, io.Discard, io.Discard, InteractiveOptions{})
	if err == nil {
		t.Fatal("an ambiguous row must not be resumed")
	}
	if !strings.Contains(err.Error(), "is ambiguous") {
		t.Fatalf("err=%v, want an ambiguity error", err)
	}
	if stub.admit != 0 {
		t.Fatalf("ambiguous resume admitted %d commands", stub.admit)
	}
}

// TestInteractiveHistoryRejectsOfflineEndpoint proves endpoint scope revalidates
// connectivity at query time, not at entry time.
//
// Entering an endpoint does not require it to be online, so an endpoint can be
// entered while connected and disconnect before the history query is dispatched.
// The query therefore resolves the endpoint again instead of trusting the scope.
func TestInteractiveHistoryRejectsOfflineEndpoint(t *testing.T) {
	stub := historyScenarioStub([]protocol.HistoryRow{{ProviderSessionID: "wa-past", Resumable: true}}, historyReport())
	stub.interactiveStub.endpoints[0].ConnectionState = "offline"

	_, diagnostics := runScope(t, stub, "cd host-one/endpoint-1\nhistory\nexit\n", ColorPolicy{})
	want := `endpoint "endpoint-1" is not online: connection_state=offline`
	if !strings.Contains(diagnostics, want) {
		t.Fatalf("diagnostics=%q, want %q", diagnostics, want)
	}
	if len(stub.historyCalls) != 0 {
		t.Fatalf("offline endpoint reached the history API: %v", stub.historyCalls)
	}
}

// TestInteractiveHistoryReadsWholeProviderWindow proves the REPL never narrows a
// history read. An operator selects a row from what is rendered, so a hidden limit
// would make a row unreachable with no way to ask for it.
func TestInteractiveHistoryReadsWholeProviderWindow(t *testing.T) {
	stub := historyScenarioStub([]protocol.HistoryRow{
		{ProviderSessionID: "wa-past", Resumable: true, ResourceID: "res-past"},
	}, historyReport())

	if _, diagnostics := runScope(t, stub, "history endpoint-1\nexit\n", ColorPolicy{}); diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if len(stub.historyLimits) != 1 || stub.historyLimits[0] != 0 {
		t.Fatalf("limits=%v want=[0]", stub.historyLimits)
	}
}

// TestInteractiveResumeAcceptsUnverifiedRow covers the recovery path a container
// restart requires. The provider still reports the session, but no process holds
// it, so the Endpoint reports no generation. Resume must be admitted, because it
// addresses the provider session by handle and is the only operation able to
// recover the row; refusing it would leave the operator with no recovery step.
func TestInteractiveResumeAcceptsUnverifiedRow(t *testing.T) {
	stub := historyScenarioStub(
		[]protocol.HistoryRow{{ProviderSessionID: "wa-dead", Resumable: true, ResourceID: "res-dead"}},
		historyReport(historyLiveSession("res-dead", "wa-dead", "")),
	)

	output, diagnostics := runScope(t, stub, "history endpoint-1\nresume 1\ny\nexit\n", ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("unverified row must be resumable, diagnostics=%q", diagnostics)
	}
	if stub.admit != 1 {
		t.Fatalf("admitted=%d want=1", stub.admit)
	}
	intent := stub.intents[0]
	if intent.Operation != protocol.OperationAgentResume {
		t.Fatalf("wrong operation: %+v", intent)
	}
	if intent.Target == nil || intent.Target.ResourceID != "res-dead" || intent.Target.Generation != "" {
		t.Fatalf("wrong resume target: %+v", intent.Target)
	}
	if !strings.Contains(output, "history row numbers are stale after resume; run history to refresh") {
		t.Fatalf("missing row invalidation notice: %q", output)
	}
}

// TestInteractiveHistoryCDRejectsUnverifiedRow guards the other half of the same
// decision: an unverified row is visible but cannot be entered, because entering
// it would require a generation that does not exist. The message must name the
// real reason instead of claiming the row is not live.
func TestInteractiveHistoryCDRejectsUnverifiedRow(t *testing.T) {
	stub := historyScenarioStub(
		[]protocol.HistoryRow{{ProviderSessionID: "wa-dead", Resumable: true, ResourceID: "res-dead"}},
		historyReport(historyLiveSession("res-dead", "wa-dead", "")),
	)

	_, diagnostics := runScope(t, stub, "history endpoint-1\ncd 1\nexit\n", ColorPolicy{})
	want := `history row 1 is unverified on endpoint "endpoint-1": the session record exists but no process holds it, so it cannot be entered; use resume 1 to resume it`
	if !strings.Contains(diagnostics, want) {
		t.Fatalf("diagnostics=%q, want %q", diagnostics, want)
	}
}

// unverifiedSession builds one session the provider listed but could not prove
// live, so it carries no generation. It is the only shape resume accepts from the
// list table, because it is the only case where a session is visible but cannot be
// entered.
func unverifiedSession(resourceID, providerSessionID, displayName string) protocol.Session {
	return protocol.Session{
		SessionID:         resourceID,
		ProviderSessionID: providerSessionID,
		DisplayName:       displayName,
		Generation:        "",
		State:             protocol.SessionStateUnknown,
		StateReason:       protocol.StateReasonLivenessUnverified,
	}
}

// TestInteractiveResumeAcceptsUnknownListRow proves the list table can supply the
// resume target.
//
// Before this, resume required a history namespace, and history is a different
// provider surface that does not contain an unverified session at all. The row was
// therefore visible in the list and unreachable by the only operation able to
// recover it, so the operator had no recovery step.
func TestInteractiveResumeAcceptsUnknownListRow(t *testing.T) {
	stub := historyScenarioStub(nil, historyReport(unverifiedSession("res-dead", "wa-dead", "dead work")))

	output, diagnostics := runScope(t, stub, "list\nresume 1\ny\nexit\n", ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("unknown list row must be resumable, diagnostics=%q", diagnostics)
	}
	if stub.admit != 1 {
		t.Fatalf("admitted=%d want=1", stub.admit)
	}
	intent := stub.intents[0]
	if intent.Operation != protocol.OperationAgentResume || intent.EndpointID != "endpoint-1" {
		t.Fatalf("wrong resume intent: %+v", intent)
	}
	if intent.Target == nil || intent.Target.ResourceID != "res-dead" || intent.Target.Generation != "" {
		t.Fatalf("wrong resume target: %+v", intent.Target)
	}
	if !strings.Contains(output, "list row numbers are stale after resume; run list to refresh") {
		t.Fatalf("missing list invalidation notice: %q", output)
	}
}

// TestInteractiveResumeRejectsLiveListRow proves a list row with a generation is
// entered rather than resumed, so resume can never start a second runtime for a
// session that is already running.
func TestInteractiveResumeRejectsLiveListRow(t *testing.T) {
	stub := historyScenarioStub(nil, historyReport(historyLiveSession("res-live", "wa-live", "gen-1")))

	_, diagnostics := runScope(t, stub, "list\nresume 1\nexit\n", ColorPolicy{})
	want := `row 1 is live on endpoint "endpoint-1", so it cannot be resumed; use cd 1 to enter it`
	if !strings.Contains(diagnostics, want) {
		t.Fatalf("diagnostics=%q, want %q", diagnostics, want)
	}
	if stub.admit != 0 {
		t.Fatalf("live list row admitted %d commands", stub.admit)
	}
}

// TestInteractiveResumeRejectsNonUnknownListRow proves only an unknown session is
// resumable from the list. A stopped session is a different condition: the provider
// proved no process holds it, so it is not a resume candidate from this table.
func TestInteractiveResumeRejectsNonUnknownListRow(t *testing.T) {
	stopped := protocol.Session{SessionID: "res-stopped", ProviderSessionID: "wa-stopped", State: "stopped"}
	stub := historyScenarioStub(nil, historyReport(stopped))

	_, diagnostics := runScope(t, stub, "list\nresume 1\nexit\n", ColorPolicy{})
	want := `row 1 is "stopped" on endpoint "endpoint-1", so it cannot be resumed; only an unknown session can be resumed from the list`
	if !strings.Contains(diagnostics, want) {
		t.Fatalf("diagnostics=%q, want %q", diagnostics, want)
	}
	if stub.admit != 0 {
		t.Fatalf("non-unknown list row admitted %d commands", stub.admit)
	}
}

// TestInteractiveResumeBareAcceptsSoleUnknownSession proves a bare resume recovers
// the only unknown session without the operator having to read a row number first.
func TestInteractiveResumeBareAcceptsSoleUnknownSession(t *testing.T) {
	stub := historyScenarioStub(nil, historyReport(
		historyLiveSession("res-live", "wa-live", "gen-1"),
		unverifiedSession("res-dead", "wa-dead", "dead work"),
	))

	output, diagnostics := runScope(t, stub, "list\nresume\ny\nexit\n", ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("sole unknown session must be resumable, diagnostics=%q", diagnostics)
	}
	if stub.admit != 1 {
		t.Fatalf("admitted=%d want=1", stub.admit)
	}
	intent := stub.intents[0]
	if intent.Target == nil || intent.Target.ResourceID != "res-dead" || intent.Target.Generation != "" {
		t.Fatalf("bare resume selected the wrong target: %+v", intent.Target)
	}
	if !strings.Contains(output, "list row numbers are stale after resume; run list to refresh") {
		t.Fatalf("missing list invalidation notice: %q", output)
	}
}

// TestInteractiveResumeBareRejectsSeveralUnknownSessions proves the uniqueness
// guard. With two unknown rows there is no way to tell which one was meant, and
// resuming the wrong session would start a runtime nobody asked for, so the
// ambiguity is reported with the candidate row numbers instead of being resolved
// by position.
func TestInteractiveResumeBareRejectsSeveralUnknownSessions(t *testing.T) {
	stub := historyScenarioStub(nil, historyReport(
		unverifiedSession("res-a", "wa-a", "first work"),
		unverifiedSession("res-b", "wa-b", "second work"),
	))

	_, diagnostics := runScope(t, stub, "list\nresume\nexit\n", ColorPolicy{})
	want := "2 unknown sessions are listed (1, 2), so a bare resume is ambiguous; run resume <row> to choose one"
	if !strings.Contains(diagnostics, want) {
		t.Fatalf("diagnostics=%q, want %q", diagnostics, want)
	}
	if stub.admit != 0 {
		t.Fatalf("ambiguous bare resume admitted %d commands", stub.admit)
	}
}

// TestInteractiveResumeBareIgnoresLiveSessions proves the uniqueness guard counts
// only unknown sessions. A live session is not a resume candidate, so its presence
// must not make a sole unknown session look ambiguous.
func TestInteractiveResumeBareIgnoresLiveSessions(t *testing.T) {
	stub := historyScenarioStub(nil, historyReport(
		historyLiveSession("res-live-a", "wa-live-a", "gen-1"),
		unverifiedSession("res-dead", "wa-dead", "dead work"),
		historyLiveSession("res-live-b", "wa-live-b", "gen-2"),
	))

	_, diagnostics := runScope(t, stub, "list\nresume\ny\nexit\n", ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("live rows must not make a sole unknown session ambiguous, diagnostics=%q", diagnostics)
	}
	if stub.admit != 1 {
		t.Fatalf("admitted=%d want=1", stub.admit)
	}
	if intent := stub.intents[0]; intent.Target == nil || intent.Target.ResourceID != "res-dead" {
		t.Fatalf("bare resume selected the wrong target: %+v", intent.Target)
	}
}

// TestInteractiveResumeRejectsUnknownListRowWithGeneration proves the generation
// guard is load-bearing on its own.
//
// The state check alone cannot reject this row, because the reported state really is
// unknown. A generation was nevertheless reported, so the provider did prove a live
// process, and resuming would start a second runtime for it. The generation check is
// therefore the only site that refuses the row, and it must run before the state
// check so the operator is told to enter the session rather than told the state is
// wrong.
func TestInteractiveResumeRejectsUnknownListRowWithGeneration(t *testing.T) {
	contradictory := protocol.Session{
		SessionID:         "res-odd",
		ProviderSessionID: "wa-odd",
		Generation:        "gen-1",
		State:             protocol.SessionStateUnknown,
	}
	stub := historyScenarioStub(nil, historyReport(contradictory))

	_, diagnostics := runScope(t, stub, "list\nresume 1\nexit\n", ColorPolicy{})
	want := `row 1 is live on endpoint "endpoint-1", so it cannot be resumed; use cd 1 to enter it`
	if !strings.Contains(diagnostics, want) {
		t.Fatalf("diagnostics=%q, want %q", diagnostics, want)
	}
	if stub.admit != 0 {
		t.Fatalf("unknown row with a generation admitted %d commands", stub.admit)
	}
}
