package main

import (
	"os"
	"strings"
	"testing"
)

// TestServerHandlerUsesConfiguredScopes guards the production wiring of operator
// scopes. The scope set is only enforced when the handler is built with
// NewHandlerWithScopes; the older constructors delegate to it with a nil scope
// list, which AuthorizeOperation treats as unrestricted. Reverting this call
// silently disables every scope check, so the wiring is asserted here rather
// than left to review.
func TestServerHandlerUsesConfiguredScopes(t *testing.T) {
	source, err := os.ReadFile("main.go")
	if err != nil {
		t.Fatalf("read main.go: %v", err)
	}
	text := string(source)

	if !strings.Contains(text, "NewHandlerWithScopes(") {
		t.Fatal("main.go does not build the API handler with NewHandlerWithScopes, so configured operator scopes are ignored")
	}
	if !strings.Contains(text, "cfg.AuthScopes") {
		t.Fatal("main.go does not pass cfg.AuthScopes to the API handler")
	}
	for _, legacy := range []string{
		"NewHandlerWithCommandsAndBrokerAndOutputAndRefresh(",
		"NewHandlerWithCommandsAndBrokerAndOutput(",
		"NewHandlerWithCommandsAndBroker(",
		"NewHandlerWithCommands(",
	} {
		if strings.Contains(text, legacy) {
			t.Fatalf("main.go still calls %s, which discards the configured scopes", legacy)
		}
	}
}
