package main

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

// infoTestServer serves two endpoints whose inventories share no session IDs,
// plus one provider session ID that appears on both, so a test can prove the
// resource-ID namespace wins and that a cross-endpoint provider match is
// rejected instead of silently resolved.
func infoTestServer(t *testing.T) *httptest.Server {
	t.Helper()
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("Authorization") != "Bearer test-token" {
			writeListTestEnvelope(w, http.StatusUnauthorized, "unauthorized", nil)
			return
		}
		switch r.URL.Path {
		case "/api/v1/endpoints":
			writeListTestEnvelope(w, http.StatusOK, "success", []protocol.Endpoint{
				{EndpointID: "endpoint-1", DisplayName: "endpoint-1", ConnectionState: "online"},
				{EndpointID: "endpoint-2", DisplayName: "endpoint-2", ConnectionState: "online"},
			})
		case "/api/v1/endpoints/endpoint-1/session-state":
			writeListTestEnvelope(w, http.StatusOK, "success", protocol.InventoryReport{
				ReportComplete:   true,
				CollectionStatus: protocol.CollectionSucceeded,
				Sessions: []protocol.Session{{
					SessionID:         "res-1",
					ProviderSessionID: "shared-provider",
					ProjectWorkspace:  "/work/project-one",
					Generation:        "gen-1",
					State:             "running",
				}},
			})
		case "/api/v1/endpoints/endpoint-2/session-state":
			writeListTestEnvelope(w, http.StatusOK, "success", protocol.InventoryReport{
				ReportComplete:   true,
				CollectionStatus: protocol.CollectionSucceeded,
				Sessions: []protocol.Session{{
					SessionID:         "res-2",
					ProviderSessionID: "shared-provider",
					ProjectWorkspace:  "/work/project-two",
					Generation:        "gen-2",
					State:             "idle",
				}},
			})
		default:
			writeListTestEnvelope(w, http.StatusNotFound, "not found", nil)
		}
	}))
	t.Cleanup(server.Close)
	return server
}

// runInfo executes the standalone info command against the fixture server.
func runInfo(t *testing.T, server *httptest.Server, args ...string) (string, error) {
	t.Helper()
	var output, diagnostics strings.Builder
	full := append([]string{"--server-url", server.URL, "--token", "test-token"}, args...)
	err := runWithIO(full, strings.NewReader(""), &output, &diagnostics, false, nil)
	return output.String(), err
}

// TestInfoHelpAndDispatchContract proves the advertised syntax is executable and
// that the rendered detail comes from the persisted inventory.
func TestInfoHelpAndDispatchContract(t *testing.T) {
	var helpOut, helpDiagnostics strings.Builder
	if err := runWithIO([]string{"help", "info"}, strings.NewReader(""), &helpOut, &helpDiagnostics, false, nil); err != nil {
		t.Fatal(err)
	}
	const syntax = "agent-cluster-cli [options] info <session-id>"
	if !strings.Contains(helpOut.String(), syntax) {
		t.Fatalf("help=%q missing executable syntax %q", helpOut.String(), syntax)
	}
	server := infoTestServer(t)
	output, err := runInfo(t, server, "info", "res-1")
	if err != nil {
		t.Fatal(err)
	}
	for _, want := range []string{"session_id: res-1", "project_workspace: /work/project-one", "endpoint_id: endpoint-1"} {
		if !strings.Contains(output, want) {
			t.Fatalf("output=%q missing %q", output, want)
		}
	}
}

// TestInfoRejectsEndpointIdentifier proves an endpoint ID is not silently
// rendered as a session, and that the error points at the command that can show
// endpoint detail.
func TestInfoRejectsEndpointIdentifier(t *testing.T) {
	server := infoTestServer(t)
	_, err := runInfo(t, server, "info", "endpoint-1")
	if err == nil {
		t.Fatal("info accepted an endpoint identifier")
	}
	if !strings.Contains(err.Error(), "not a session") || !strings.Contains(err.Error(), "show endpoint-1") {
		t.Fatalf("unexpected error: %v", err)
	}
}

// TestInfoPrefersResourceIDOverProviderSessionID proves the routing identity
// wins when the two identifier namespaces collide.
func TestInfoPrefersResourceIDOverProviderSessionID(t *testing.T) {
	server := infoTestServer(t)
	output, err := runInfo(t, server, "info", "res-2")
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(output, "session_id: res-2") || !strings.Contains(output, "endpoint_id: endpoint-2") {
		t.Fatalf("output=%q did not resolve the resource ID", output)
	}
}

// TestInfoRejectsAmbiguousProviderSessionID proves a provider session ID that
// exists on several endpoints is an error rather than an arbitrary pick.
func TestInfoRejectsAmbiguousProviderSessionID(t *testing.T) {
	server := infoTestServer(t)
	_, err := runInfo(t, server, "info", "shared-provider")
	if err == nil {
		t.Fatal("info resolved an ambiguous provider session ID")
	}
	if !strings.Contains(err.Error(), "matches 2 endpoints") {
		t.Fatalf("unexpected error: %v", err)
	}
}

// TestInfoJSONEnvelopeCarriesEndpointAndSession proves the machine-readable form
// names the owning endpoint, so a caller never infers ownership from a label.
func TestInfoJSONEnvelopeCarriesEndpointAndSession(t *testing.T) {
	server := infoTestServer(t)
	output, err := runInfo(t, server, "--json", "info", "res-1")
	if err != nil {
		t.Fatal(err)
	}
	// The standalone JSON form renders the value directly, matching show --json,
	// so a caller parses the top-level object rather than an envelope.
	var info struct {
		EndpointID string           `json:"endpoint_id"`
		Session    protocol.Session `json:"session"`
	}
	if err := json.Unmarshal([]byte(output), &info); err != nil {
		t.Fatalf("output=%q is not JSON: %v", output, err)
	}
	if info.EndpointID != "endpoint-1" || info.Session.SessionID != "res-1" {
		t.Fatalf("unexpected info document: %+v", info)
	}
	if info.Session.ProjectWorkspace != "/work/project-one" {
		t.Fatalf("project workspace was dropped: %+v", info.Session)
	}
}

// TestInfoRejectsUnknownAndMissingIdentifiers proves both a missing argument and
// an unknown identifier fail instead of rendering an empty detail.
func TestInfoRejectsUnknownAndMissingIdentifiers(t *testing.T) {
	server := infoTestServer(t)
	if _, err := runInfo(t, server, "info"); err == nil || !strings.Contains(err.Error(), "usage: info <session-id>") {
		t.Fatalf("missing identifier gave %v", err)
	}
	if _, err := runInfo(t, server, "info", "no-such-session"); err == nil || !strings.Contains(err.Error(), "was not found") {
		t.Fatalf("unknown identifier gave %v", err)
	}
}
