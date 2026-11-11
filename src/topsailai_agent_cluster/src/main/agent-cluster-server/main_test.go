package main

import (
	"os"
	"strings"
	"testing"
)

// TestServerHandlerWiresOutputAndRefresh guards the production wiring of the API
// handler. The Server forwards output reads and forced collections through the
// same handler, so building it with a narrower constructor silently drops one of
// those seams. The wiring is asserted here rather than left to review.
//
// The Server holds no operator scope concept: authorization belongs to the
// Endpoint that owns the machine, so a scope list must not reappear in this file.
func TestServerHandlerWiresOutputAndRefresh(t *testing.T) {
	source, err := os.ReadFile("main.go")
	if err != nil {
		t.Fatalf("read main.go: %v", err)
	}
	text := string(source)

	if !strings.Contains(text, "NewHandlerWithCommandsAndBrokerAndOutputAndRefresh(") {
		t.Fatal("main.go does not build the API handler with output and refresh forwarding")
	}
	for _, removed := range []string{
		"NewHandlerWithScopes(",
		"cfg.AuthScopes",
		"AGENT_CLUSTER_AUTH_SCOPES",
	} {
		if strings.Contains(text, removed) {
			t.Fatalf("main.go still references %s, which the Server no longer holds", removed)
		}
	}
}
