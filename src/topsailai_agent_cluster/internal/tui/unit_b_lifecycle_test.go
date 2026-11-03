package tui

import (
	"context"
	"errors"
	"fmt"
	"io"
	"reflect"
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

func TestUnitBS3InvalidListPreservesOnlyBeforeValidationAndRecovers(t *testing.T) {
	stub := scopeStub()
	state := interactiveState{}
	state.enterEndpoint(stub.endpoints[0])
	old := SessionRow{No: 1, EndpointID: "old", SessionID: "old", Generation: "old"}
	state.setRows([]SessionRow{old})
	var output, diagnostics strings.Builder
	if err := interactiveList(context.Background(), stub, &state, "endpoint-2", false, &output, &diagnostics, ColorPolicy{}); err == nil {
		t.Fatal("expected invalid scoped list filter")
	}
	if got := state.Rows[1]; got != old {
		t.Fatalf("invalid list changed old binding: %+v", state.Rows)
	}
	if err := interactiveList(context.Background(), stub, &state, "", false, &output, &diagnostics, ColorPolicy{}); err != nil {
		t.Fatalf("successful recovery: %v", err)
	}
	if _, ok := state.Rows[1]; !ok {
		t.Fatal("successful recovery did not publish new rows")
	}
}

func TestUnitBS3PartialTableWriteFailureLeavesRowsEmpty(t *testing.T) {
	stub := scopeStub()
	state := interactiveState{}
	state.setRows([]SessionRow{{No: 1, SessionID: "old", Generation: "old"}})
	writer := &unitBFailAfterWriter{remaining: 3}
	err := interactiveList(context.Background(), stub, &state, "", false, writer, io.Discard, ColorPolicy{})
	if err == nil {
		t.Fatal("expected partial table writer failure")
	}
	if len(state.Rows) != 0 {
		t.Fatalf("rows published after partial write failure: %+v", state.Rows)
	}
}

func TestUnitBS3PublishesRowsOnlyAfterEveryOutputAndDiagnosticWrite(t *testing.T) {
	stub := scopeStub()
	state := interactiveState{}
	state.setRows([]SessionRow{{No: 1, SessionID: "old", Generation: "old"}})
	observer := &unitBObservingWriter{state: &state}
	if err := interactiveList(context.Background(), stub, &state, "", false, observer, io.Discard, ColorPolicy{}); err == nil {
		t.Fatal("expected render failure")
	}
	if observer.sawRows {
		t.Fatal("rows became visible while table output was still being rendered")
	}

	state.setRows([]SessionRow{{No: 1, SessionID: "old", Generation: "old"}})
	diagnosticFailure := &unitBFailingWriter{}
	if err := interactiveList(context.Background(), &unitBDiagnosticAPI{interactiveStub: scopeStub()}, &state, "", false, io.Discard, diagnosticFailure, ColorPolicy{}); err == nil {
		t.Fatal("expected diagnostic write failure")
	}
	if len(state.Rows) != 0 {
		t.Fatalf("rows published after diagnostic failure: %+v", state.Rows)
	}
}

// TestUnitBS3PublishesOnlyAfterSuccessfulTableAndDiagnostics observes a complete
// table render and verifies that staged rows stay hidden until diagnostics finish.
func TestUnitBS3PublishesOnlyAfterSuccessfulTableAndDiagnostics(t *testing.T) {
	stub := scopeStub()
	state := interactiveState{}
	state.setRows([]SessionRow{{No: 1, EndpointID: "old", SessionID: "old", Generation: "old"}})
	observer := &unitBSuccessfulObservingWriter{state: &state}
	if err := interactiveList(context.Background(), &unitBDiagnosticAPI{interactiveStub: stub}, &state, "", false, observer, io.Discard, ColorPolicy{}); err != nil {
		t.Fatalf("successful render: %v", err)
	}
	if observer.sawRows {
		t.Fatal("rows became visible during successful table rendering")
	}
	if len(state.Rows) == 0 {
		t.Fatal("successful list did not publish rows")
	}
}

// TestUnitBS3InvalidSyntaxPreservesBindings verifies that a syntactically
// invalid list never starts replacement and therefore keeps the old binding.
func TestUnitBS3InvalidSyntaxPreservesBindings(t *testing.T) {
	stub := scopeStub()
	state := interactiveState{}
	state.enterEndpoint(stub.endpoints[0])
	old := SessionRow{No: 1, EndpointID: "old", SessionID: "old", Generation: "old"}
	state.setRows([]SessionRow{old})
	beforeList, beforeInventory := stub.listCalls, stub.inventoryCalls
	var output, diagnostics strings.Builder
	quit, err := executeInteractiveLine(context.Background(), stub, &state, "list --bad-flag", nil, &output, &output, &diagnostics, InteractiveOptions{})
	if err == nil || quit {
		t.Fatalf("invalid list result: quit=%t err=%v", quit, err)
	}
	if state.Rows[1] != old {
		t.Fatalf("invalid syntax changed old binding: %+v", state.Rows)
	}
	if stub.listCalls != beforeList || stub.inventoryCalls != beforeInventory {
		t.Fatalf("invalid syntax performed API calls: list=%d inventory=%d", stub.listCalls, stub.inventoryCalls)
	}
}

// TestUnitBS3SuccessfulListReplacesOldBindings verifies that a later successful
// refresh publishes only the newly rendered rows.
func TestUnitBS3SuccessfulListReplacesOldBindings(t *testing.T) {
	stub := scopeStub()
	state := interactiveState{}
	oldRows := make([]SessionRow, 100)
	for i := range oldRows {
		oldRows[i] = SessionRow{No: i + 1, EndpointID: "old", SessionID: fmt.Sprintf("old-%d", i+1), Generation: "old-generation"}
	}
	state.setRows(oldRows)
	var output, diagnostics strings.Builder
	if err := interactiveList(context.Background(), stub, &state, "", false, &output, &diagnostics, ColorPolicy{}); err != nil {
		t.Fatalf("initial successful list: %v", err)
	}
	if len(state.Rows) != 2 {
		t.Fatalf("initial rows=%d want=2", len(state.Rows))
	}
	stub.failList = true
	if err := interactiveList(context.Background(), stub, &state, "", false, &output, &diagnostics, ColorPolicy{}); err == nil {
		t.Fatal("expected injected list failure")
	}
	if len(state.Rows) != 0 {
		t.Fatalf("failed replacement retained rows: %+v", state.Rows)
	}
	if _, ok := state.Rows[99]; ok {
		t.Fatal("failed replacement retained old row 99")
	}
	if err := interactiveList(context.Background(), stub, &state, "", false, &output, &diagnostics, ColorPolicy{}); err != nil {
		t.Fatalf("successful recovery: %v", err)
	}
	if len(state.Rows) != 2 || state.Rows[1].SessionID == "old-1" {
		t.Fatalf("recovery did not publish new bindings: %+v", state.Rows)
	}
	if _, ok := state.Rows[99]; ok {
		t.Fatal("recovery published an unrelated old row 99")
	}
}

// TestUnitBB4AuthorityMatrixRejectsWithoutSelectionMutation covers stale,
// unknown, removed, incomplete and generation-changing authority results.
func TestUnitBB4AuthorityMatrixRejectsWithoutSelectionMutation(t *testing.T) {
	cases := []struct {
		name   string
		mutate func(protocol.InventoryReport) protocol.InventoryReport
		want   string
	}{
		{"stale", func(r protocol.InventoryReport) protocol.InventoryReport { r.Sessions[0].Stale = true; return r }, "not fresh"},
		{"unknown", func(r protocol.InventoryReport) protocol.InventoryReport { r.Sessions[0].Unknown = true; return r }, "not fresh"},
		{"removed", func(r protocol.InventoryReport) protocol.InventoryReport { r.Sessions = nil; return r }, "no longer identifies"},
		{"incomplete", func(r protocol.InventoryReport) protocol.InventoryReport { r.ReportComplete = false; return r }, "unavailable"},
		{"generation", func(r protocol.InventoryReport) protocol.InventoryReport {
			r.Sessions[0].Generation = "changed"
			return r
		}, "generation changed"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			stub := singleHostStub()
			state := interactiveState{}
			state.setRows([]SessionRow{{No: 1, EndpointID: "endpoint-1", SessionID: "res-1", Generation: "generation-1"}})
			before := state
			stub.reports["endpoint-1"] = tc.mutate(stub.reports["endpoint-1"])
			if tc.name == "unavailable" {
				stub.inventoryErr = errors.New("inventory load failed")
			}
			err := cdRowNumber(&state, stub, context.Background(), 1)
			if err == nil || !strings.Contains(err.Error(), tc.want) {
				t.Fatalf("error = %v, want %q", err, tc.want)
			}
			if state.Scope != before.Scope || state.SessionID != before.SessionID {
				t.Fatalf("authority failure mutated selection: before=%+v after=%+v", before, state)
			}
		})
	}
}

// TestUnitBB4CompleteAuthorityFailureMatrix covers unavailable and adapter
// authority failures in addition to session freshness failures.
func TestUnitBB4CompleteAuthorityFailureMatrix(t *testing.T) {
	cases := []struct {
		name   string
		mutate func(protocol.InventoryReport) protocol.InventoryReport
		want   string
	}{
		{name: "unavailable", mutate: func(r protocol.InventoryReport) protocol.InventoryReport { return r }, want: "inventory is unavailable"},
		{name: "empty-generation", mutate: func(r protocol.InventoryReport) protocol.InventoryReport { r.Sessions[0].Generation = ""; return r }, want: "generation changed"},
		{name: "adapter-stale", mutate: func(r protocol.InventoryReport) protocol.InventoryReport { r.Adapters[0].Stale = true; return r }, want: "adapter"},
		{name: "adapter-unknown", mutate: func(r protocol.InventoryReport) protocol.InventoryReport { r.Adapters[0].DataKnown = false; return r }, want: "adapter"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			stub := singleHostStub()
			state := interactiveState{}
			state.setRows([]SessionRow{{No: 1, EndpointID: "endpoint-1", SessionID: "res-1", Generation: "generation-1"}})
			before := state
			stub.reports["endpoint-1"] = tc.mutate(stub.reports["endpoint-1"])
			if tc.name == "unavailable" {
				stub.inventoryErr = errors.New("inventory load failed")
			}
			err := cdRowNumber(&state, stub, context.Background(), 1)
			if err == nil || !strings.Contains(err.Error(), tc.want) {
				t.Fatalf("error=%v want=%q", err, tc.want)
			}
			if state.Scope != before.Scope || state.EndpointID != before.EndpointID || state.SessionID != before.SessionID || state.Generation != before.Generation || state.Invalidated != before.Invalidated || state.InvalidReason != before.InvalidReason {
				t.Fatalf("authority failure mutated selection: before=%+v after=%+v", before, state)
			}
		})
	}
}

// TestUnitBS3DiagnosticFailureClearsOldIdentityAndRecoveryPublishesNewIdentity
// verifies both sides of the failed diagnostic replacement lifecycle.
func TestUnitBS3DiagnosticFailureClearsOldIdentityAndRecoveryPublishesNewIdentity(t *testing.T) {
	stub := scopeStub()
	state := interactiveState{}
	oldRows := []SessionRow{{No: 1, EndpointID: "old-endpoint", SessionID: "session-A", Generation: "generation-A"}}
	state.setRows(oldRows)
	failing := &unitBDiagnosticAPI{interactiveStub: stub}
	failing.inventoryErr = errors.New("diagnostic fixture failure")
	var output, diagnostics strings.Builder
	if err := interactiveList(context.Background(), failing, &state, "", false, io.Discard, &unitBFailingWriter{}, ColorPolicy{}); err == nil {
		t.Fatal("expected diagnostic failure")
	}
	if len(state.Rows) != 0 {
		t.Fatalf("old bindings survived diagnostic failure: %+v", state.Rows)
	}
	stub.inventoryErr = nil
	stub.reports["endpoint-1"] = scopeInventory("session-B", "generation-B")
	if err := interactiveList(context.Background(), stub, &state, "", false, &output, &diagnostics, ColorPolicy{}); err != nil {
		t.Fatalf("recovery: %v", err)
	}
	row, ok := state.Rows[1]
	if !ok || row.SessionID != "session-B" || row.Generation != "generation-B" {
		t.Fatalf("recovery identity=%+v exists=%t", row, ok)
	}
	if row.SessionID == "session-A" || row.Generation == "generation-A" {
		t.Fatalf("recovery republished old identity: %+v", row)
	}
}

// TestUnitBB4FailedReplacementInvalidatesBothNumericSpellings verifies that a
// failed replacement cannot reuse a stale row through either navigation spelling.
func TestUnitBB4FailedReplacementInvalidatesBothNumericSpellings(t *testing.T) {
	for _, input := range []string{"1", "cd 1"} {
		t.Run(input, func(t *testing.T) {
			stub := scopeStub()
			state := interactiveState{}
			state.setRows([]SessionRow{{No: 99, EndpointID: "old", SessionID: "session-old", Generation: "generation-old"}})
			before := state
			stub.failList = true
			var output, diagnostics strings.Builder
			if err := interactiveList(context.Background(), stub, &state, "", false, &output, &diagnostics, ColorPolicy{}); err == nil {
				t.Fatal("expected replacement failure")
			}
			if len(state.Rows) != 0 {
				t.Fatalf("failed replacement retained rows: %+v", state.Rows)
			}
			beforeList, beforeInventory := stub.listCalls, stub.inventoryCalls
			_, err := executeInteractiveLine(context.Background(), stub, &state, input, nil, &output, &output, &diagnostics, InteractiveOptions{})
			if err == nil {
				t.Fatalf("stale spelling %q unexpectedly succeeded", input)
			}
			if state.Scope != before.Scope || state.EndpointID != before.EndpointID || state.SessionID != before.SessionID || state.Generation != before.Generation {
				t.Fatalf("failed replacement changed selection: before=%+v after=%+v", before, state)
			}
			if stub.listCalls != beforeList || stub.inventoryCalls != beforeInventory {
				t.Fatalf("stale spelling queried authority: %d/%d -> %d/%d", beforeList, beforeInventory, stub.listCalls, stub.inventoryCalls)
			}
		})
	}
}

// TestUnitBB4ReplacementOutcomeMatrix verifies published identities and named
// clean/refresh replacement behavior through the interactive dispatcher.
func assertUnitBRows(t *testing.T, rows map[int]SessionRow, want map[int]SessionRow) {
	t.Helper()
	if !reflect.DeepEqual(rows, want) {
		t.Fatalf("rows=%+v want=%+v", rows, want)
	}
}

// TestUnitBB4ReplacementOutcomeMatrix verifies complete clean and refresh replacement lifecycles.
func TestUnitBB4ReplacementOutcomeMatrix(t *testing.T) {
	t.Run("clean", func(t *testing.T) {
		stub := scopeStub()
		state := interactiveState{}
		var output, diagnostics strings.Builder
		if _, err := executeInteractiveLine(context.Background(), stub, &state, "list", nil, &output, &output, &diagnostics, InteractiveOptions{}); err != nil {
			t.Fatalf("initial list: %v", err)
		}
		oldRows := cloneUnitBState(state).Rows
		if len(oldRows) != 2 {
			t.Fatalf("initial bindings=%+v want both endpoints", oldRows)
		}
		stub.inventoryErrors = map[string]error{"endpoint-2": errors.New("failed endpoint")}
		if _, err := executeInteractiveLine(context.Background(), stub, &state, "list --clean", nil, &output, &output, &diagnostics, InteractiveOptions{}); err != nil {
			t.Fatalf("clean list: %v", err)
		}
		want := map[int]SessionRow{1: oldRows[1]}
		assertUnitBRows(t, state.Rows, want)
		if _, ok := state.Rows[2]; ok {
			t.Fatal("clean retained the old failed endpoint binding")
		}
		cleanList, cleanInventory := stub.listCalls, stub.inventoryCalls
		if cleanList != 2 || cleanInventory != 4 {
			t.Fatalf("clean calls list=%d inventory=%d", cleanList, cleanInventory)
		}
		if _, err := executeInteractiveLine(context.Background(), stub, &state, "2", nil, &output, &output, &diagnostics, InteractiveOptions{}); err == nil || !strings.Contains(err.Error(), "out of range") {
			t.Fatalf("old row navigation error=%v", err)
		}
		if stub.listCalls != cleanList || stub.inventoryCalls != cleanInventory {
			t.Fatalf("old row navigation queried API: list=%d/%d inventory=%d/%d", cleanList, stub.listCalls, cleanInventory, stub.inventoryCalls)
		}
		if _, err := executeInteractiveLine(context.Background(), stub, &state, "1", nil, &output, &output, &diagnostics, InteractiveOptions{}); err != nil {
			t.Fatalf("new binding navigation: %v", err)
		}
		if !strings.Contains(diagnostics.String(), "endpoint endpoint-2 unavailable") {
			t.Fatalf("clean diagnostics=%q", diagnostics.String())
		}
	})

	t.Run("refresh", func(t *testing.T) {
		stub := scopeStub()
		state := interactiveState{}
		var output, diagnostics strings.Builder
		if _, err := executeInteractiveLine(context.Background(), stub, &state, "list", nil, &output, &output, &diagnostics, InteractiveOptions{}); err != nil {
			t.Fatalf("initial list: %v", err)
		}
		stub.reports["endpoint-1"] = scopeInventory("refresh-session", "refresh-generation")
		stub.reports["endpoint-2"] = scopeInventory("refresh-session-2", "refresh-generation-2")
		if _, err := executeInteractiveLine(context.Background(), stub, &state, "refresh", nil, &output, &output, &diagnostics, InteractiveOptions{}); err != nil {
			t.Fatalf("refresh: %v", err)
		}
		want := ListRows(stub.endpoints, stub.reports, "")
		assignRowNumbers(want)
		assertUnitBRows(t, state.Rows, map[int]SessionRow{1: want[0], 2: want[1]})
		if stub.listCalls != 2 || stub.inventoryCalls != 4 {
			t.Fatalf("refresh calls list=%d inventory=%d", stub.listCalls, stub.inventoryCalls)
		}
	})
}

// cloneUnitBState creates an independent snapshot of all mutable navigation state.
func cloneUnitBState(state interactiveState) interactiveState {
	clone := state
	if state.Rows == nil {
		return clone
	}
	clone.Rows = make(map[int]SessionRow, len(state.Rows))
	for number, row := range state.Rows {
		cloneRow := row
		if row.LastSuccessAtMS != nil {
			lastSuccess := *row.LastSuccessAtMS
			cloneRow.LastSuccessAtMS = &lastSuccess
		}
		clone.Rows[number] = cloneRow
	}
	return clone
}

// assertUnitBStateEqual compares the complete navigation snapshot, including
// every captured row field and the pointed-to last-success timestamp.
func assertUnitBStateEqual(t *testing.T, got, want interactiveState) {
	t.Helper()
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("state=%+v want=%+v", got, want)
	}
}

// TestUnitBB2BareAndExplicitRejectionsUseIndependentStateSnapshots compares
// every required rejection and authority branch through both numeric spellings.
func TestUnitBB2BareAndExplicitRejectionsUseIndependentStateSnapshots(t *testing.T) {
	cases := []struct {
		name  string
		input string
		setup func(*interactiveStub, *interactiveState)
	}{
		{name: "zero", input: "0", setup: func(_ *interactiveStub, state *interactiveState) {
			state.setRows([]SessionRow{{No: 1, EndpointID: "endpoint-1", AdapterID: "adapter-1", SessionID: "res-1", DisplayName: "one", Generation: "generation-1", State: "running", CollectionStatus: "succeeded"}})
		}},
		{name: "out-of-range", input: "9", setup: func(_ *interactiveStub, state *interactiveState) {
			state.setRows([]SessionRow{{No: 1, EndpointID: "endpoint-1", AdapterID: "adapter-1", SessionID: "res-1", DisplayName: "one", Generation: "generation-1", State: "running", CollectionStatus: "succeeded"}})
		}},
		{name: "overflow", input: strings.Repeat("9", 64), setup: func(_ *interactiveStub, state *interactiveState) {
			state.setRows([]SessionRow{{No: 1, EndpointID: "endpoint-1", AdapterID: "adapter-1", SessionID: "res-1", DisplayName: "one", Generation: "generation-1", State: "running", CollectionStatus: "succeeded"}})
		}},
		{name: "surplus-space", input: "1 foo", setup: func(_ *interactiveStub, state *interactiveState) {
			state.setRows([]SessionRow{{No: 1, EndpointID: "endpoint-1", AdapterID: "adapter-1", SessionID: "res-1", DisplayName: "one", Generation: "generation-1", State: "running", CollectionStatus: "succeeded"}})
		}},
		{name: "surplus-tab", input: "1\tfoo", setup: func(_ *interactiveStub, state *interactiveState) {
			state.setRows([]SessionRow{{No: 1, EndpointID: "endpoint-1", AdapterID: "adapter-1", SessionID: "res-1", DisplayName: "one", Generation: "generation-1", State: "running", CollectionStatus: "succeeded"}})
		}},
		{name: "generation-mismatch", input: "1", setup: func(stub *interactiveStub, state *interactiveState) {
			state.setRows([]SessionRow{{No: 1, EndpointID: "endpoint-1", AdapterID: "adapter-1", SessionID: "res-1", DisplayName: "one", Generation: "generation-1", State: "running", CollectionStatus: "succeeded"}})
			stub.reports["endpoint-1"] = scopeInventory("res-1", "generation-2")
		}},
		{name: "duplicate-id", input: "1", setup: func(stub *interactiveStub, state *interactiveState) {
			state.setRows([]SessionRow{{No: 1, EndpointID: "endpoint-1", AdapterID: "adapter-1", SessionID: "res-1", DisplayName: "one", Generation: "generation-1", State: "running", CollectionStatus: "succeeded"}})
			report := scopeInventory("res-1", "generation-1")
			report.Sessions = append(report.Sessions, report.Sessions[0])
			stub.reports["endpoint-1"] = report
		}},
		{name: "session-scope", input: "1", setup: func(_ *interactiveStub, state *interactiveState) {
			state.enterSession(protocol.Endpoint{EndpointID: "endpoint-1", Hostname: "host-one"}, "res-1", "generation-1")
		}},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			inputs := []string{tc.input, "cd " + tc.input}
			var wantErr string
			var wantState interactiveState
			var wantRows map[int]SessionRow
			var wantList, wantInventory int
			for index, input := range inputs {
				stub := scopeStub()
				state := interactiveState{}
				tc.setup(stub, &state)
				before := cloneUnitBState(state)
				var output, diagnostics strings.Builder
				_, err := executeInteractiveLine(context.Background(), stub, &state, input, nil, &output, &output, &diagnostics, InteractiveOptions{})
				if err == nil {
					t.Fatalf("%q unexpectedly succeeded", input)
				}
				assertUnitBStateEqual(t, state, before)
				if index == 0 {
					wantErr = err.Error()
					wantState = cloneUnitBState(state)
					wantRows = cloneUnitBState(state).Rows
					wantList, wantInventory = stub.listCalls, stub.inventoryCalls
					continue
				}
				if tc.name == "surplus-space" || tc.name == "surplus-tab" {
					wantExplicitErr := fmt.Sprintf("endpoint %q was not found", tc.input)
					if err.Error() != wantExplicitErr || stub.listCalls != 1 || stub.inventoryCalls != 2 {
						t.Fatalf("explicit surplus mismatch input=%q err=%q want=%q calls=%d/%d", input, err, wantExplicitErr, stub.listCalls, stub.inventoryCalls)
					}
					continue
				}
				if err.Error() != wantErr || !reflect.DeepEqual(state.Rows, wantRows) || stub.listCalls != wantList || stub.inventoryCalls != wantInventory {
					t.Fatalf("bare/explicit mismatch input=%q err=%q state=%+v rows=%+v calls=%d/%d want err=%q state=%+v rows=%+v calls=%d/%d", input, err, state, state.Rows, stub.listCalls, stub.inventoryCalls, wantErr, wantState, wantRows, wantList, wantInventory)
				}
			}
		})
	}
}

// TestUnitBB2QualifiedEndpointPathUsesIndependentExplicitState verifies the
// qualified explicit path without conflating it with numeric rejection grammar.
func TestUnitBB2QualifiedEndpointPathUsesIndependentExplicitState(t *testing.T) {
	inputs := []string{"1", "cd host-one/endpoint-1/res-1"}
	for _, input := range inputs {
		stub := scopeStub()
		state := interactiveState{}
		if input == "1" {
			state.setRows([]SessionRow{{No: 1, EndpointID: "endpoint-1", AdapterID: "adapter-1", SessionID: "res-1", Generation: "generation-1", CollectionStatus: protocol.CollectionSucceeded}})
		}
		var output, diagnostics strings.Builder
		if _, err := executeInteractiveLine(context.Background(), stub, &state, input, nil, &output, &output, &diagnostics, InteractiveOptions{}); err != nil {
			t.Fatalf("path %q: %v", input, err)
		}
		if state.Scope.Kind != ScopeSession || state.Scope.EndpointID != "endpoint-1" || state.Scope.SessionID != "res-1" {
			t.Fatalf("path %q state=%+v", input, state)
		}
		wantInventory := 2
		if input == "1" {
			wantInventory = 1
		}
		if stub.listCalls != 1 || stub.inventoryCalls != wantInventory {
			t.Fatalf("path %q calls list=%d inventory=%d want inventory=%d", input, stub.listCalls, stub.inventoryCalls, wantInventory)
		}
	}
}

// TestUnitBB2AuthorityBranchesUseIndependentNumericSpellings compares every
// authority rejection through bare and explicit numeric navigation.
func TestUnitBB2AuthorityBranchesUseIndependentNumericSpellings(t *testing.T) {
	cases := []struct {
		name  string
		setup func(*interactiveStub, *interactiveState)
	}{
		{name: "no-bindings", setup: func(_ *interactiveStub, _ *interactiveState) {}},
		{name: "empty-session-id", setup: func(_ *interactiveStub, state *interactiveState) {
			state.setRows([]SessionRow{{No: 1, EndpointID: "endpoint-1", AdapterID: "adapter-1", Generation: "generation-1"}})
		}},
		{name: "empty-generation", setup: func(_ *interactiveStub, state *interactiveState) {
			state.setRows([]SessionRow{{No: 1, EndpointID: "endpoint-1", AdapterID: "adapter-1", SessionID: "res-1"}})
		}},
		{name: "inventory-unavailable", setup: func(stub *interactiveStub, state *interactiveState) {
			state.setRows([]SessionRow{{No: 1, EndpointID: "endpoint-1", AdapterID: "adapter-1", SessionID: "res-1", Generation: "generation-1"}})
			stub.inventoryErr = errors.New("inventory load failed")
		}},
		{name: "inventory-incomplete", setup: func(stub *interactiveStub, state *interactiveState) {
			state.setRows([]SessionRow{{No: 1, EndpointID: "endpoint-1", AdapterID: "adapter-1", SessionID: "res-1", Generation: "generation-1"}})
			report := stub.reports["endpoint-1"]
			report.ReportComplete = false
			stub.reports["endpoint-1"] = report
		}},
		{name: "session-removed", setup: func(stub *interactiveStub, state *interactiveState) {
			state.setRows([]SessionRow{{No: 1, EndpointID: "endpoint-1", AdapterID: "adapter-1", SessionID: "res-1", Generation: "generation-1"}})
			report := stub.reports["endpoint-1"]
			report.Sessions = nil
			stub.reports["endpoint-1"] = report
		}},
		{name: "stale-session", setup: func(stub *interactiveStub, state *interactiveState) {
			state.setRows([]SessionRow{{No: 1, EndpointID: "endpoint-1", AdapterID: "adapter-1", SessionID: "res-1", Generation: "generation-1"}})
			report := stub.reports["endpoint-1"]
			report.Sessions[0].Stale = true
			stub.reports["endpoint-1"] = report
		}},
		{name: "adapter-authority", setup: func(stub *interactiveStub, state *interactiveState) {
			state.setRows([]SessionRow{{No: 1, EndpointID: "endpoint-1", AdapterID: "adapter-1", SessionID: "res-1", Generation: "generation-1"}})
			report := stub.reports["endpoint-1"]
			report.Adapters[0].DataKnown = false
			stub.reports["endpoint-1"] = report
		}},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			var wantErr string
			var wantState interactiveState
			var wantList, wantInventory int
			for index, input := range []string{"1", "cd 1"} {
				stub := scopeStub()
				state := interactiveState{}
				tc.setup(stub, &state)
				before := cloneUnitBState(state)
				var output, diagnostics strings.Builder
				_, err := executeInteractiveLine(context.Background(), stub, &state, input, nil, &output, &output, &diagnostics, InteractiveOptions{})
				if err == nil {
					t.Fatalf("%q unexpectedly succeeded", input)
				}
				assertUnitBStateEqual(t, state, before)
				if index == 0 {
					wantErr, wantState = err.Error(), cloneUnitBState(state)
					wantList, wantInventory = stub.listCalls, stub.inventoryCalls
					continue
				}
				if err.Error() != wantErr || !reflect.DeepEqual(state, wantState) || stub.listCalls != wantList || stub.inventoryCalls != wantInventory {
					t.Fatalf("bare/explicit mismatch input=%q err=%q state=%+v calls=%d/%d want err=%q state=%+v calls=%d/%d", input, err, state, stub.listCalls, stub.inventoryCalls, wantErr, wantState, wantList, wantInventory)
				}
			}
		})
	}
}
