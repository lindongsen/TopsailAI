package embedded

import (
	"encoding/base64"
	"strings"
	"testing"
)

// setEmbedded replaces the three package-level values for one test and restores
// them afterwards.
//
// The values are package-level because `-X` can only set a package-level string,
// so a test that set them without restoring would leak a token into every later
// test in this package. The cleanup is not optional.
func setEmbedded(t *testing.T, serverURL, tunnelToken, policyBase64 string) {
	t.Helper()
	previousURL, previousToken, previousPolicy := ServerURL, TunnelToken, PolicyBase64
	t.Cleanup(func() {
		ServerURL, TunnelToken, PolicyBase64 = previousURL, previousToken, previousPolicy
	})
	ServerURL, TunnelToken, PolicyBase64 = serverURL, tunnelToken, policyBase64
}

// TestEnabledIsFalseInANormalBuild pins the property the whole package rests on:
// a build that embedded nothing must be indistinguishable from a build that
// predates this package.
func TestEnabledIsFalseInANormalBuild(t *testing.T) {
	setEmbedded(t, "", "", "")

	if Enabled() {
		t.Fatal("Enabled() = true for a build that embedded nothing")
	}
	if CarriesSecret() {
		t.Fatal("CarriesSecret() = true for a build that embedded nothing")
	}
}

// TestEnabledIsTrueForAnyEmbeddedValue covers each value on its own, because a
// build may embed only the Server URL and must still be recognised as embedded.
func TestEnabledIsTrueForAnyEmbeddedValue(t *testing.T) {
	cases := []struct {
		name      string
		serverURL string
		token     string
		policy    string
	}{
		{name: "server url only", serverURL: "wss://example.test/channel"},
		{name: "token only", token: "a-token"},
		{name: "policy only", policy: base64.StdEncoding.EncodeToString([]byte("version: 1\n"))},
	}

	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			setEmbedded(t, testCase.serverURL, testCase.token, testCase.policy)
			if !Enabled() {
				t.Fatal("Enabled() = false for a build that embedded a value")
			}
		})
	}
}

// TestCarriesSecretTracksOnlyTheToken is the test that matters for the deny list.
//
// A build with a Server URL and a policy discloses nothing by being read, so it
// must not be refused through a scope. Only the token makes the executable a
// credential. A test that asserted "embedded implies refused" would pass while
// breaking the install-directory case.
func TestCarriesSecretTracksOnlyTheToken(t *testing.T) {
	cases := []struct {
		name      string
		serverURL string
		token     string
		policy    string
		want      bool
	}{
		{
			name:      "server url and policy without a token",
			serverURL: "wss://example.test/channel",
			policy:    base64.StdEncoding.EncodeToString([]byte("version: 1\n")),
			want:      false,
		},
		{
			name:  "token present",
			token: "a-token",
			want:  true,
		},
		{
			name:      "token present alongside the others",
			serverURL: "wss://example.test/channel",
			token:     "a-token",
			policy:    base64.StdEncoding.EncodeToString([]byte("version: 1\n")),
			want:      true,
		},
	}

	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			setEmbedded(t, testCase.serverURL, testCase.token, testCase.policy)
			if got := CarriesSecret(); got != testCase.want {
				t.Fatalf("CarriesSecret() = %v, want %v", got, testCase.want)
			}
		})
	}
}

// TestPolicyReturnsNilWhenNothingWasEmbedded keeps "no policy" distinguishable
// from "a policy that failed to decode", which is what lets LoadConfig fall back
// to the policy file instead of reporting a decode error.
func TestPolicyReturnsNilWhenNothingWasEmbedded(t *testing.T) {
	setEmbedded(t, "", "", "")

	decoded, err := Policy()
	if err != nil {
		t.Fatalf("Policy() returned an error for an empty value: %v", err)
	}
	if decoded != nil {
		t.Fatalf("Policy() = %q, want nil", decoded)
	}
}

// TestPolicyDecodesAnEmbeddedDocument checks the round trip, including a newline,
// because a policy document is multi-line and a decoder that dropped the trailing
// newline would still pass a single-line test.
func TestPolicyDecodesAnEmbeddedDocument(t *testing.T) {
	document := "version: 1\nscopes:\n  project:\n    path: /tmp\n"
	setEmbedded(t, "", "", base64.StdEncoding.EncodeToString([]byte(document)))

	decoded, err := Policy()
	if err != nil {
		t.Fatalf("Policy() returned an error: %v", err)
	}
	if string(decoded) != document {
		t.Fatalf("Policy() = %q, want %q", decoded, document)
	}
}

// TestPolicyRefusesMalformedBase64 covers the packaging mistake. The error must
// name the decode step so an operator reading a startup failure knows which value
// is wrong, and it must not echo the value itself, because the value is a policy
// document that may name paths.
func TestPolicyRefusesMalformedBase64(t *testing.T) {
	setEmbedded(t, "", "", "not base64!!")

	decoded, err := Policy()
	if err == nil {
		t.Fatal("Policy() accepted malformed base64")
	}
	if decoded != nil {
		t.Fatalf("Policy() = %q alongside an error, want nil", decoded)
	}
	if !strings.Contains(err.Error(), "decode the embedded policy") {
		t.Fatalf("error %q does not name the decode step", err)
	}
	if strings.Contains(err.Error(), "not base64!!") {
		t.Fatalf("error %q echoes the embedded value", err)
	}
}
