package main

import (
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

// noTruncateSessionID exceeds the SESSION_ID column cap, so a bounded layout
// clips it even when the output is redirected and no terminal width is known.
func noTruncateSessionID() string {
	return "session-" + strings.Repeat("0123456789", 6)
}

// newNoTruncateServer serves one endpoint whose session id exceeds the column
// cap, so a test can compare the bounded and the full rendering of one document.
func newNoTruncateServer(t *testing.T) *httptest.Server {
	t.Helper()
	sessionID := noTruncateSessionID()
	return httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("Authorization") != "Bearer test-token" {
			writeListTestEnvelope(w, http.StatusUnauthorized, "unauthorized", nil)
			return
		}
		switch r.URL.Path {
		case "/api/v1/endpoints":
			writeListTestEnvelope(w, http.StatusOK, "success", []protocol.Endpoint{
				{EndpointID: "endpoint-1", DisplayName: "endpoint-1", ConnectionState: "online"},
			})
		case "/api/v1/endpoints/endpoint-1/session-state":
			writeListTestEnvelope(w, http.StatusOK, "success", listTestInventory(sessionID))
		default:
			writeListTestEnvelope(w, http.StatusNotFound, "not found", nil)
		}
	}))
}

// TestNoTruncateFlagKeepsFullValues proves the switch is accepted by the
// standalone CLI and that it stops the column caps from clipping a value.
func TestNoTruncateFlagKeepsFullValues(t *testing.T) {
	server := newNoTruncateServer(t)
	defer server.Close()
	sessionID := noTruncateSessionID()
	base := []string{"--server-url", server.URL, "--token", "test-token", "--endpoint", "endpoint-1", "list", "--clean"}
	var bounded, full, diagnostics strings.Builder
	if err := runWithIO(base, strings.NewReader(""), &bounded, &diagnostics, false, nil); err != nil {
		t.Fatalf("bounded list failed: %v diagnostics=%q", err, diagnostics.String())
	}
	if strings.Contains(bounded.String(), sessionID) {
		t.Fatalf("bounded list kept the over-cap value: %q", bounded.String())
	}
	fullArgs := append([]string{"--no-truncate"}, base...)
	if err := runWithIO(fullArgs, strings.NewReader(""), &full, &diagnostics, false, nil); err != nil {
		t.Fatalf("--no-truncate list failed: %v diagnostics=%q", err, diagnostics.String())
	}
	if !strings.Contains(full.String(), sessionID) {
		t.Fatalf("--no-truncate truncated the value: %q", full.String())
	}
	if strings.Contains(full.String(), "...") {
		t.Fatalf("--no-truncate emitted a truncation marker: %q", full.String())
	}
}

// TestNoTruncateFlagIsAdvertised proves the switch appears in the flag usage, so
// an operator can discover it without reading the source.
func TestNoTruncateFlagIsAdvertised(t *testing.T) {
	var output, diagnostics strings.Builder
	// A help request succeeds, so the usage block is written to stdout.
	err := runWithIO([]string{"-h"}, strings.NewReader(""), &output, &diagnostics, false, nil)
	if err != nil {
		t.Fatalf("error=%v", err)
	}
	if !strings.Contains(output.String(), "-no-truncate") {
		t.Fatalf("usage=%q does not advertise --no-truncate", output.String())
	}
}

// TestNoTruncateAppliesToEndpoints proves the switch is global, so the endpoint
// projection honours it as well.
func TestNoTruncateAppliesToEndpoints(t *testing.T) {
	hostname := "host-" + strings.Repeat("q", 60)
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("Authorization") != "Bearer test-token" {
			writeListTestEnvelope(w, http.StatusUnauthorized, "unauthorized", nil)
			return
		}
		if r.URL.Path != "/api/v1/endpoints" {
			writeListTestEnvelope(w, http.StatusNotFound, "not found", nil)
			return
		}
		writeListTestEnvelope(w, http.StatusOK, "success", []protocol.Endpoint{
			{EndpointID: "endpoint-1", Hostname: hostname, ConnectionState: "online"},
		})
	}))
	defer server.Close()
	var output, diagnostics strings.Builder
	args := []string{"--no-truncate", "--server-url", server.URL, "--token", "test-token", "endpoints"}
	if err := runWithIO(args, strings.NewReader(""), &output, &diagnostics, false, nil); err != nil {
		t.Fatalf("endpoints failed: %v diagnostics=%q", err, diagnostics.String())
	}
	if !strings.Contains(output.String(), hostname) {
		t.Fatalf("--no-truncate truncated the hostname: %q", output.String())
	}
}
