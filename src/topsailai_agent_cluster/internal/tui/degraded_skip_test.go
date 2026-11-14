package tui

import (
	"context"
	"errors"
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

// degradedProbeAPI counts forced-collection calls, which is the seam that sends
// a frame to the machine. A degraded endpoint must never receive one.
type degradedProbeAPI struct {
	*runnerStubAPI
	refreshCalls []string
}

func (a *degradedProbeAPI) RefreshInventory(_ context.Context, endpointID string) (protocol.InventoryReport, error) {
	a.refreshCalls = append(a.refreshCalls, endpointID)
	return protocol.InventoryReport{CollectionStatus: protocol.CollectionSucceeded}, nil
}

// degradedProbeFixture builds one online endpoint and one degraded endpoint
// whose inventory is gone, which is the state degradation leaves behind.
func degradedProbeFixture() *degradedProbeAPI {
	return &degradedProbeAPI{runnerStubAPI: &runnerStubAPI{
		endpoints: []protocol.Endpoint{
			{EndpointID: "live-ep", ConnectionState: "online"},
			{EndpointID: "deg-ep", ConnectionState: "degraded", ExpiresAtMS: 1797000000000},
		},
		reports:         map[string]protocol.InventoryReport{},
		inventoryErrors: map[string]error{"deg-ep": errors.New("not_found: inventory not found")},
	}}
}

// TestStartupNeverQueriesDegradedEndpoint proves the startup list sends no
// request to a degraded endpoint and prints no count for it.
//
// The count is asserted absent because a degraded endpoint keeps its row: the
// operator can see it, so a summary line would only repeat what the table
// already shows. The row itself must survive, because hiding a record that still
// exists would look like proof that it was deleted.
func TestStartupNeverQueriesDegradedEndpoint(t *testing.T) {
	api := degradedProbeFixture()
	var out, errOut strings.Builder
	if err := runStartupList(context.Background(), api, &interactiveState{}, &interruptController{}, &out, &errOut, ColorPolicy{}); err != nil {
		t.Fatalf("runStartupList: %v", err)
	}
	for _, call := range api.calls {
		if call == "inventory:deg-ep" {
			t.Fatalf("startup queried a degraded endpoint: %v", api.calls)
		}
	}
	if strings.Contains(out.String(), "offline endpoints hidden") {
		t.Fatalf("startup printed a hidden count: %q", out.String())
	}
	if !strings.Contains(out.String(), "deg-ep") {
		t.Fatalf("startup dropped the degraded row: %q", out.String())
	}
	if errOut.String() != "" {
		t.Fatalf("startup wrote a diagnostic: %q", errOut.String())
	}
}

// TestListAllNeverQueriesDegradedEndpoint proves --all widens visibility without
// widening reach: the degraded endpoint is listed but never queried.
func TestListAllNeverQueriesDegradedEndpoint(t *testing.T) {
	api := degradedProbeFixture()
	var out, diagnostics strings.Builder
	if err := (CommandRunner{API: api}).ListWithOptions(context.Background(), &out, &diagnostics, "", false, TableOptions{All: true}); err != nil {
		t.Fatalf("ListWithOptions: %v", err)
	}
	for _, call := range api.calls {
		if call == "inventory:deg-ep" {
			t.Fatalf("--all queried a degraded endpoint: %v", api.calls)
		}
	}
	if strings.Contains(diagnostics.String(), "unavailable") {
		t.Fatalf("--all printed a fetch diagnostic: %q", diagnostics.String())
	}
	if !strings.Contains(out.String(), "deg-ep") {
		t.Fatalf("--all dropped the degraded row: %q", out.String())
	}
}

// TestRefreshNeverReachesDegradedEndpoint proves every refresh form refuses,
// including the two that name the endpoint explicitly.
//
// An explicit filter and --all both widen the selection, and a forced collection
// is a request to the machine. Widening what the operator may see must never
// widen what the client may contact, so the degraded check runs before the
// explicit and --all overrides rather than after them.
func TestRefreshNeverReachesDegradedEndpoint(t *testing.T) {
	for _, tc := range []struct {
		name   string
		filter string
		all    bool
	}{
		{name: "default"},
		{name: "all", all: true},
		{name: "explicit", filter: "deg-ep"},
		{name: "explicit-all", filter: "deg-ep", all: true},
	} {
		t.Run(tc.name, func(t *testing.T) {
			api := degradedProbeFixture()
			if _, err := forceCollectionSelected(context.Background(), api, tc.filter, tc.all, nil); err != nil {
				t.Fatalf("forceCollectionSelected: %v", err)
			}
			for _, id := range api.refreshCalls {
				if id == "deg-ep" {
					t.Fatalf("refresh reached a degraded endpoint: %v", api.refreshCalls)
				}
			}
		})
	}
}

// TestRefreshNamedDegradedEndpointReportsDegraded proves a named degraded
// endpoint answers with its state instead of the misleading "not found".
//
// The refusal leaves no report and no error, so without an explicit check the
// caller would conclude the endpoint is absent. The endpoint is not absent: its
// record exists and carries the deletion date, which is the fact the operator
// needs to decide whether to re-register it.
func TestRefreshNamedDegradedEndpointReportsDegraded(t *testing.T) {
	api := degradedProbeFixture()
	var out, diagnostics strings.Builder
	err := (CommandRunner{API: api}).Refresh(context.Background(), &out, &diagnostics, "deg-ep", false, TableOptions{})
	if err == nil {
		t.Fatalf("refresh of a degraded endpoint returned nil, want a refusal")
	}
	if !strings.Contains(err.Error(), "degraded") {
		t.Fatalf("err=%q, want it to name the degraded state", err.Error())
	}
	if strings.Contains(err.Error(), "not found") {
		t.Fatalf("err=%q, want it not to claim the endpoint is absent", err.Error())
	}
}

// TestListHiddenCountExcludesDegradedEndpoints proves the hidden count reports
// only the offline endpoints.
//
// The count exists because a skipped endpoint loses its row, so the operator
// would otherwise read an empty table as proof that the endpoint holds no
// sessions. A degraded endpoint keeps its row, so counting it would report a
// hidden endpoint that is not hidden.
func TestListHiddenCountExcludesDegradedEndpoints(t *testing.T) {
	api := &runnerStubAPI{
		endpoints: []protocol.Endpoint{
			{EndpointID: "live-ep", ConnectionState: "online"},
			{EndpointID: "off-ep", ConnectionState: "offline"},
			{EndpointID: "deg-ep", ConnectionState: "degraded", ExpiresAtMS: 1797000000000},
		},
		reports:         map[string]protocol.InventoryReport{},
		inventoryErrors: map[string]error{},
	}
	var out, diagnostics strings.Builder
	if err := (CommandRunner{API: api}).ListWithOptions(context.Background(), &out, &diagnostics, "", false, TableOptions{}); err != nil {
		t.Fatalf("ListWithOptions: %v", err)
	}
	if !strings.Contains(out.String(), "offline endpoints hidden: 1 (use --all to include)") {
		t.Fatalf("count=%q, want exactly the one offline endpoint", out.String())
	}
	if !strings.Contains(out.String(), "deg-ep") {
		t.Fatalf("degraded row missing: %q", out.String())
	}
	if strings.Contains(out.String(), "off-ep") {
		t.Fatalf("offline row should stay hidden: %q", out.String())
	}
}

// TestShowDegradedEndpointReportsDegraded proves show names the degraded state
// instead of claiming the endpoint is absent.
//
// show is a store read, so it stays permitted for a degraded endpoint. It cannot
// find a session there because the inventory is gone, and FindSession can only
// match an endpoint that has a committed document, so the degraded state must be
// reported before the absence.
func TestShowDegradedEndpointReportsDegraded(t *testing.T) {
	api := &runnerStubAPI{
		endpoints: []protocol.Endpoint{
			{EndpointID: "deg-ep", ConnectionState: "degraded", ExpiresAtMS: 1797000000000},
		},
		reports:         map[string]protocol.InventoryReport{},
		inventoryErrors: map[string]error{"deg-ep": errors.New("not_found: inventory not found")},
	}
	var out strings.Builder
	err := (CommandRunner{API: api}).Show(context.Background(), &out, "deg-ep", false)
	if err == nil {
		t.Fatalf("show of a degraded endpoint returned nil, want a refusal")
	}
	if !strings.Contains(err.Error(), "degraded") {
		t.Fatalf("err=%q, want it to name the degraded state", err.Error())
	}
	if strings.Contains(err.Error(), "not found") {
		t.Fatalf("err=%q, want it not to claim the endpoint is absent", err.Error())
	}
}

// TestShowOfflineEndpointKeepsAbsenceAnswer proves the degraded branch does not
// widen into every non-online state.
//
// An offline endpoint may come back, so its missing inventory is a transient
// condition rather than a scheduled deletion. Reporting it as degraded would
// tell the operator to re-register a machine that only needs restarting.
func TestShowOfflineEndpointKeepsAbsenceAnswer(t *testing.T) {
	api := &runnerStubAPI{
		endpoints: []protocol.Endpoint{
			{EndpointID: "off-ep", ConnectionState: "offline"},
		},
		reports:         map[string]protocol.InventoryReport{},
		inventoryErrors: map[string]error{"off-ep": errors.New("not_found: inventory not found")},
	}
	var out strings.Builder
	err := (CommandRunner{API: api}).Show(context.Background(), &out, "off-ep", false)
	if err == nil {
		t.Fatalf("show of an offline endpoint returned nil")
	}
	if strings.Contains(err.Error(), "degraded") {
		t.Fatalf("err=%q, want the offline endpoint not to be called degraded", err.Error())
	}
}
