package tui

import (
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

// TestFindSessionAcceptsTheHostnameTheListRenders proves that the identifier an
// operator reads in the ENDPOINT column can be used as a target.
//
// The list renders the endpoint hostname in that column, so an operator who copies
// the cell types a hostname. Before this test the lookup matched only the endpoint
// ID, the cluster session ID and the provider session ID, so the copied value was
// refused with "endpoint or session ... was not found" while the row was on screen.
// The failure named the target as absent, which sends the investigation to the
// inventory instead of to the lookup.
//
// The history resolver already accepted a hostname, so the two surfaces disagreed
// about which names address an endpoint. This test pins the shared lookup to the
// same rule, and it fails when the hostname branch is removed.
func TestFindSessionAcceptsTheHostnameTheListRenders(t *testing.T) {
	endpoints := []protocol.Endpoint{{EndpointID: "ac.ai-dev", Hostname: "ai-dev"}}
	reports := map[string]protocol.InventoryReport{"ac.ai-dev": {}}

	endpoint, _, session, err := FindSession("ai-dev", endpoints, reports)
	if err != nil {
		t.Fatalf("the hostname rendered in the ENDPOINT column was refused: %v", err)
	}
	if endpoint.EndpointID != "ac.ai-dev" {
		t.Fatalf("hostname resolved to endpoint %q, want %q", endpoint.EndpointID, "ac.ai-dev")
	}
	if session != nil {
		t.Fatalf("hostname resolved to a session %#v, want the endpoint itself", session)
	}
}

// TestFindSessionRefusesAnAmbiguousHostname proves that two machines sharing a
// hostname are refused instead of resolved to the first match.
//
// Picking one would address a machine the operator did not name, and the operator
// would have no way to tell which one was chosen. The message must name both IDs so
// the next command can be exact.
func TestFindSessionRefusesAnAmbiguousHostname(t *testing.T) {
	endpoints := []protocol.Endpoint{
		{EndpointID: "ac.b", Hostname: "shared"},
		{EndpointID: "ac.a", Hostname: "shared"},
	}
	reports := map[string]protocol.InventoryReport{"ac.a": {}, "ac.b": {}}

	_, _, _, err := FindSession("shared", endpoints, reports)
	if err == nil {
		t.Fatal("an ambiguous hostname was resolved to one endpoint, so the operator cannot tell which machine was addressed")
	}
	for _, want := range []string{"ac.a", "ac.b", "several endpoints"} {
		if !strings.Contains(err.Error(), want) {
			t.Fatalf("ambiguity message %q does not contain %q", err.Error(), want)
		}
	}
}

// TestFindSessionKeepsEndpointIDPrecedenceOverHostname proves the new branch did
// not change which identifier wins.
//
// An endpoint whose ID equals another endpoint's hostname is the case that would
// break if the hostname branch ran first. The ID must still win, because it is the
// durable identity and the hostname is descriptive.
func TestFindSessionKeepsEndpointIDPrecedenceOverHostname(t *testing.T) {
	endpoints := []protocol.Endpoint{
		{EndpointID: "ac.a", Hostname: "other"},
		{EndpointID: "ac.b", Hostname: "ac.a"},
	}
	reports := map[string]protocol.InventoryReport{"ac.a": {}, "ac.b": {}}

	endpoint, _, _, err := FindSession("ac.a", endpoints, reports)
	if err != nil {
		t.Fatalf("endpoint ID was refused: %v", err)
	}
	if endpoint.EndpointID != "ac.a" {
		t.Fatalf("resolved to %q, want the endpoint whose ID is %q", endpoint.EndpointID, "ac.a")
	}
}
