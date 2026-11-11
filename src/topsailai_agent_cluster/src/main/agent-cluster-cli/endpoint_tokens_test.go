package main

import (
	"testing"
)

// TestParseEndpointTokensAcceptsPairs verifies the documented mapping format.
func TestParseEndpointTokensAcceptsPairs(t *testing.T) {
	tokens, err := parseEndpointTokens("gd-dev=abc123, topsailai-dev=def456")
	if err != nil {
		t.Fatalf("parse endpoint tokens: %v", err)
	}
	if tokens["gd-dev"] != "abc123" {
		t.Fatalf("gd-dev token = %q, want abc123", tokens["gd-dev"])
	}
	if tokens["topsailai-dev"] != "def456" {
		t.Fatalf("topsailai-dev token = %q, want def456", tokens["topsailai-dev"])
	}
}

// TestParseEndpointTokensEmptyYieldsNoMapping verifies that an unset value is not
// an error, because an Endpoint with no policy directory accepts every caller.
func TestParseEndpointTokensEmptyYieldsNoMapping(t *testing.T) {
	for _, value := range []string{"", "   "} {
		tokens, err := parseEndpointTokens(value)
		if err != nil {
			t.Fatalf("parse %q: %v", value, err)
		}
		if len(tokens) != 0 {
			t.Fatalf("parse %q produced %d entries, want 0", value, len(tokens))
		}
	}
}

// TestParseEndpointTokensRejectsMalformedEntries verifies that a typo is reported
// instead of skipped, because a skipped entry would look like an Endpoint refusal.
func TestParseEndpointTokensRejectsMalformedEntries(t *testing.T) {
	cases := map[string]string{
		"missing separator":  "gd-dev",
		"missing token":      "gd-dev=",
		"missing endpoint":   "=abc123",
		"empty entry":        "gd-dev=abc123,,topsailai-dev=def456",
		"token with comma":   "gd-dev=abc,123",
		"token with equals":  "gd-dev=abc=123",
		"duplicate endpoint": "gd-dev=abc123,gd-dev=def456",
	}
	for name, value := range cases {
		if _, err := parseEndpointTokens(value); err == nil {
			t.Fatalf("%s: parse %q succeeded, want an error", name, value)
		}
	}
}

// TestApplyEndpointTokenFlagRequiresEndpoint verifies that a token is never
// applied to an unnamed target, because that would send one machine's credential
// to whichever machine a command happened to address.
func TestApplyEndpointTokenFlagRequiresEndpoint(t *testing.T) {
	tokens := map[string]string{}
	if err := applyEndpointTokenFlag(tokens, "", "abc123"); err == nil {
		t.Fatal("apply without an endpoint succeeded, want an error")
	}
	if len(tokens) != 0 {
		t.Fatalf("rejected flag still recorded %d entries", len(tokens))
	}
}

// TestApplyEndpointTokenFlagRecordsOneEndpoint verifies the accepted path.
func TestApplyEndpointTokenFlagRecordsOneEndpoint(t *testing.T) {
	tokens := map[string]string{}
	if err := applyEndpointTokenFlag(tokens, "gd-dev", "abc123"); err != nil {
		t.Fatalf("apply endpoint token: %v", err)
	}
	if tokens["gd-dev"] != "abc123" {
		t.Fatalf("gd-dev token = %q, want abc123", tokens["gd-dev"])
	}
}

// TestApplyEndpointTokenFlagRejectsConflict verifies that a flag disagreeing with
// the configured mapping is refused instead of silently overriding it, because
// either choice would ignore a credential the operator stated.
func TestApplyEndpointTokenFlagRejectsConflict(t *testing.T) {
	tokens := map[string]string{"gd-dev": "abc123"}
	if err := applyEndpointTokenFlag(tokens, "gd-dev", "different"); err == nil {
		t.Fatal("conflicting token succeeded, want an error")
	}
	if tokens["gd-dev"] != "abc123" {
		t.Fatalf("conflict changed the token to %q", tokens["gd-dev"])
	}
}

// TestApplyEndpointTokenFlagAcceptsAgreement verifies that repeating the same
// token is not a conflict, so a wrapper script can pass it explicitly.
func TestApplyEndpointTokenFlagAcceptsAgreement(t *testing.T) {
	tokens := map[string]string{"gd-dev": "abc123"}
	if err := applyEndpointTokenFlag(tokens, "gd-dev", "abc123"); err != nil {
		t.Fatalf("agreeing token rejected: %v", err)
	}
}

// TestApplyEndpointTokenFlagIgnoresEmptyToken verifies that an unset flag leaves
// the mapping untouched.
func TestApplyEndpointTokenFlagIgnoresEmptyToken(t *testing.T) {
	tokens := map[string]string{"gd-dev": "abc123"}
	if err := applyEndpointTokenFlag(tokens, "gd-dev", ""); err != nil {
		t.Fatalf("empty token rejected: %v", err)
	}
	if tokens["gd-dev"] != "abc123" {
		t.Fatalf("empty token changed the mapping to %q", tokens["gd-dev"])
	}
}
