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

	// The property is that both seams are forwarded, not that one particular
	// constructor name appears. Two constructors forward both seams: the bearer
	// convenience form and the credential form a deployment uses when it selects
	// another authentication mode. Every narrower constructor drops at least one
	// seam, so naming them is what makes this guard fail for the real defect.
	full := []string{
		"NewHandlerWithCommandsAndBrokerAndOutputAndRefresh(",
		"NewHandlerWithCredential(",
	}
	used := ""
	for _, name := range full {
		if strings.Contains(text, name) {
			used = name
			break
		}
	}
	if used == "" {
		t.Fatal("main.go does not build the API handler with output and refresh forwarding")
	}
	for _, narrow := range []string{
		"NewHandler(",
		"NewHandlerWithBroker(",
		"NewHandlerWithCommands(",
		"NewHandlerWithCommandsAndBroker(",
		"NewHandlerWithCommandsAndBrokerAndOutput(",
	} {
		if strings.Contains(text, narrow) {
			t.Fatalf("main.go builds the API handler with %s, which drops an output or refresh seam", narrow)
		}
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
