package main

import (
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

// TestParseServerProfilesAcceptsPairs verifies the documented map shape.
func TestParseServerProfilesAcceptsPairs(t *testing.T) {
	profiles, err := parseServerProfiles("primary=http://127.0.0.1:8080, secondary=https://other.example.test")
	if err != nil {
		t.Fatalf("parse failed: %v", err)
	}
	if got := profiles["primary"]; got != "http://127.0.0.1:8080" {
		t.Fatalf("primary = %q", got)
	}
	if got := profiles["secondary"]; got != "https://other.example.test" {
		t.Fatalf("secondary = %q", got)
	}
}

// TestParseServerProfilesAcceptsURLWithQueryString verifies a URL carrying "=" is
// accepted. The split takes the first separator, so the value stays unambiguous,
// and refusing it would reject a legitimate address.
func TestParseServerProfilesAcceptsURLWithQueryString(t *testing.T) {
	profiles, err := parseServerProfiles("primary=http://127.0.0.1:8080/api?tenant=a")
	if err != nil {
		t.Fatalf("parse failed: %v", err)
	}
	if got := profiles["primary"]; got != "http://127.0.0.1:8080/api?tenant=a" {
		t.Fatalf("primary = %q", got)
	}
}

// TestParseServerProfileTokensAcceptsPaddedToken verifies a base64 token ending in
// "=" padding is accepted. Refusing it would reject a correct credential and
// report it as a formatting mistake.
func TestParseServerProfileTokensAcceptsPaddedToken(t *testing.T) {
	tokens, err := parseServerProfileTokens("primary=YWJjZA==")
	if err != nil {
		t.Fatalf("parse failed: %v", err)
	}
	if got := tokens["primary"]; got != "YWJjZA==" {
		t.Fatalf("primary = %q", got)
	}
}

// TestParseServerProfilesRejectsMalformedEntries verifies a typo is reported
// instead of skipped, because a skipped entry would leave the operator believing a
// profile exists while the selection silently used nothing.
func TestParseServerProfilesRejectsMalformedEntries(t *testing.T) {
	cases := map[string]string{
		"missing separator": "primary",
		"missing value":     "primary=",
		"missing name":      "=http://127.0.0.1:8080",
		"empty entry":       "primary=http://a,,secondary=http://b",
		"duplicate name":    "primary=http://a,primary=http://b",
	}
	for name, value := range cases {
		if _, err := parseServerProfiles(value); err == nil {
			t.Fatalf("%s: parse %q succeeded, want an error", name, value)
		}
	}
}

// TestParseServerProfilesEmptyYieldsNoMapping verifies an unset value is not an
// error, because a deployment that selects no profile is a valid deployment.
func TestParseServerProfilesEmptyYieldsNoMapping(t *testing.T) {
	for _, value := range []string{"", "   "} {
		profiles, err := parseServerProfiles(value)
		if err != nil {
			t.Fatalf("parse %q failed: %v", value, err)
		}
		if len(profiles) != 0 {
			t.Fatalf("parse %q produced %d entries, want 0", value, len(profiles))
		}
	}
}

// TestValidateServerProfileTokensRejectsTokenWithoutProfile verifies a token for an
// undefined profile is reported at load time. The alternative is a later "unknown
// profile" failure that describes the symptom while the configured token sits
// unused.
func TestValidateServerProfileTokensRejectsTokenWithoutProfile(t *testing.T) {
	profiles := map[string]string{"primary": "http://127.0.0.1:8080"}
	tokens := map[string]string{"secondary": "abc123"}
	err := validateServerProfileTokens(profiles, tokens)
	if err == nil {
		t.Fatal("validation succeeded, want an error")
	}
	if !strings.Contains(err.Error(), "secondary") {
		t.Fatalf("error %q does not name the undefined profile", err)
	}
}

// TestResolveServerProfileReturnsOnePair verifies the URL and token come from the
// same profile, so a selection can never pair one Server's address with another
// Server's credential.
func TestResolveServerProfileReturnsOnePair(t *testing.T) {
	profiles := map[string]string{"primary": "http://a", "secondary": "http://b"}
	tokens := map[string]string{"primary": "token-a", "secondary": "token-b"}
	url, token, err := resolveServerProfile("secondary", profiles, tokens)
	if err != nil {
		t.Fatalf("resolve failed: %v", err)
	}
	if url != "http://b" || token != "token-b" {
		t.Fatalf("resolved (%q, %q), want (http://b, token-b)", url, token)
	}
}

// TestResolveServerProfileAllowsMissingToken verifies a profile with no token is
// valid and yields an empty token, because a Server may be configured without one
// and an empty token means the CLI omits the Authorization header.
func TestResolveServerProfileAllowsMissingToken(t *testing.T) {
	profiles := map[string]string{"primary": "http://a"}
	url, token, err := resolveServerProfile("primary", profiles, nil)
	if err != nil {
		t.Fatalf("resolve failed: %v", err)
	}
	if url != "http://a" || token != "" {
		t.Fatalf("resolved (%q, %q), want (http://a, empty)", url, token)
	}
}

// TestResolveServerProfileRejectsUnknownName verifies an unknown name is refused
// with the configured names listed. A silent fallback to the built-in URL would
// talk to the wrong Server while the operator believed the profile took effect,
// and the only symptom would be an empty inventory.
func TestResolveServerProfileRejectsUnknownName(t *testing.T) {
	profiles := map[string]string{"primary": "http://a", "secondary": "http://b"}
	_, _, err := resolveServerProfile("tertiary", profiles, nil)
	if err == nil {
		t.Fatal("resolve succeeded, want an error")
	}
	for _, name := range []string{"primary", "secondary"} {
		if !strings.Contains(err.Error(), name) {
			t.Fatalf("error %q does not list configured profile %q", err, name)
		}
	}
}

// TestResolveServerProfileRejectsSelectionWithNoProfiles verifies a selection
// against an empty map names the missing definition rather than reporting an
// unknown name, because the two mistakes have different fixes.
func TestResolveServerProfileRejectsSelectionWithNoProfiles(t *testing.T) {
	_, _, err := resolveServerProfile("primary", nil, nil)
	if err == nil {
		t.Fatal("resolve succeeded, want an error")
	}
	if !strings.Contains(err.Error(), serverProfilesEnv) {
		t.Fatalf("error %q does not name the defining variable", err)
	}
}

// TestResolveServerTargetRejectsProfileWithExplicitURL verifies a profile cannot be
// combined with an explicit --server-url. Merging them is how a credential reaches
// the wrong Server: a stale flag in a shell alias would redirect the profile's
// token to a different machine and nothing in the output would show the split.
func TestResolveServerTargetRejectsProfileWithExplicitURL(t *testing.T) {
	profiles := map[string]string{"primary": "http://a"}
	_, _, err := resolveServerTarget("primary", profiles, nil, true, false, "http://stale", "")
	if err == nil {
		t.Fatal("resolve succeeded, want an error")
	}
	if !strings.Contains(err.Error(), "--server-profile") {
		t.Fatalf("error %q does not name the conflicting option", err)
	}
}

// TestResolveServerTargetRejectsProfileWithExplicitToken verifies the same refusal
// for an explicit --token, because a token is the half that must never be split
// from its address.
func TestResolveServerTargetRejectsProfileWithExplicitToken(t *testing.T) {
	profiles := map[string]string{"primary": "http://a"}
	_, _, err := resolveServerTarget("primary", profiles, nil, false, true, "", "stale-token")
	if err == nil {
		t.Fatal("resolve succeeded, want an error")
	}
}

// TestResolveServerTargetKeepsEnvironmentDefaults verifies an invocation that
// selects no profile keeps the URL and token it was given, so the environment
// fallback still works for every existing deployment.
func TestResolveServerTargetKeepsEnvironmentDefaults(t *testing.T) {
	url, token, err := resolveServerTarget("", nil, nil, false, false, "http://default", "default-token")
	if err != nil {
		t.Fatalf("resolve failed: %v", err)
	}
	if url != "http://default" || token != "default-token" {
		t.Fatalf("resolved (%q, %q), want the supplied defaults", url, token)
	}
}

// TestServerProfileSelectsURLAndTokenEndToEnd proves the profile reaches the
// Server, not merely that a resolver returns a pair.
//
// A resolver test cannot show that the selected pair is the one the client uses:
// the wiring could ignore the resolver's result and still pass every unit test
// above. This test drives the real entry point against a Server that accepts one
// token only, so a wrong URL fails to connect and a wrong token is refused with
// 401. The profile is selected through the environment variable, which is the
// path a script or shell alias uses.
func TestServerProfileSelectsURLAndTokenEndToEnd(t *testing.T) {
	const profileToken = "profile-token"
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("Authorization") != "Bearer "+profileToken {
			writeListTestEnvelope(w, http.StatusUnauthorized, "unauthorized", nil)
			return
		}
		if r.URL.Path != "/api/v1/endpoints" {
			writeListTestEnvelope(w, http.StatusNotFound, "not found", nil)
			return
		}
		writeListTestEnvelope(w, http.StatusOK, "success", []any{})
	}))
	t.Cleanup(server.Close)

	// The environment names a profile whose token is the one the Server accepts.
	// The built-in URL and token are deliberately wrong, so a build that ignored
	// the profile would fail instead of passing by accident.
	t.Setenv(serverProfilesEnv, "primary="+server.URL)
	t.Setenv(serverProfileTokensEnv, "primary="+profileToken)
	t.Setenv(serverProfileEnv, "primary")
	t.Setenv(cliServerURLEnv, "http://127.0.0.1:1")
	t.Setenv(cliServerTokenEnv, "wrong-token")
	t.Setenv(cliAuthModeEnv, "bearer")

	var output, diagnostics strings.Builder
	if err := runWithIO([]string{"list"}, strings.NewReader(""), &output, &diagnostics, false, nil); err != nil {
		t.Fatalf("list through a selected profile failed: %v", err)
	}
	if strings.Contains(output.String(), "unauthorized") {
		t.Fatalf("the Server refused the profile token, so the profile's token was not used:\n%s", output.String())
	}
}

// TestServerProfileFlagOverridesEnvironmentSelection proves the flag wins over the
// environment selection, so an operator can override a script's choice for one
// invocation without editing the environment.
func TestServerProfileFlagOverridesEnvironmentSelection(t *testing.T) {
	const flagToken = "flag-token"
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("Authorization") != "Bearer "+flagToken {
			writeListTestEnvelope(w, http.StatusUnauthorized, "unauthorized", nil)
			return
		}
		writeListTestEnvelope(w, http.StatusOK, "success", []any{})
	}))
	t.Cleanup(server.Close)

	t.Setenv(serverProfilesEnv, "from-env="+server.URL+",from-flag="+server.URL)
	t.Setenv(serverProfileTokensEnv, "from-env=env-token,from-flag="+flagToken)
	t.Setenv(serverProfileEnv, "from-env")
	t.Setenv(cliAuthModeEnv, "bearer")

	var output, diagnostics strings.Builder
	if err := runWithIO([]string{"--server-profile", "from-flag", "list"}, strings.NewReader(""), &output, &diagnostics, false, nil); err != nil {
		t.Fatalf("list with an explicit profile failed: %v", err)
	}
	if strings.Contains(output.String(), "unauthorized") {
		t.Fatalf("the Server refused the flag profile's token, so the flag did not override the environment:\n%s", output.String())
	}
}

// TestServerProfileRejectsUnknownNameEndToEnd proves an unknown selection fails
// before any request is sent, so the operator is told the name is wrong instead of
// seeing a connection failure to the built-in URL.
func TestServerProfileRejectsUnknownNameEndToEnd(t *testing.T) {
	t.Setenv(serverProfilesEnv, "primary=http://127.0.0.1:1")
	t.Setenv(serverProfileEnv, "missing")

	var output, diagnostics strings.Builder
	err := runWithIO([]string{"list"}, strings.NewReader(""), &output, &diagnostics, false, nil)
	if err == nil {
		t.Fatal("list with an unknown profile succeeded, want an error")
	}
	if !strings.Contains(err.Error(), "missing") {
		t.Fatalf("error %q does not name the unknown profile", err)
	}
}
