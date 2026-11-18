package security

import (
	"io"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

// newTestVerifier returns a verifier holding one token with a fixed clock.
func newTestVerifier(t *testing.T, token Token, now time.Time) *Verifier {
	t.Helper()
	verifier := NewVerifier(map[string]Token{token.KeyID: token}, DefaultSignatureWindow)
	verifier.Now = func() time.Time { return now }
	return verifier
}

// signAt builds a signature with an explicit timestamp.
//
// SignRequest stamps with the wall clock, which cannot match a verifier whose
// clock is pinned. Tests therefore build the signature directly so the timestamp
// they sign is the timestamp the verifier compares against.
func signAt(t *testing.T, token Token, now time.Time, build func(timestampMS int64, nonce string) string) Signature {
	t.Helper()
	nonce := NewNonce()
	if nonce == "" {
		t.Fatal("cannot generate a nonce")
	}
	timestamp := now.UnixMilli()
	return Signature{
		KeyID:       token.KeyID,
		TimestampMS: timestamp,
		Nonce:       nonce,
		Signature:   Sign(token.Secret, build(timestamp, nonce)),
	}
}

func TestCredentialAuthenticatorSelectsConfiguredMode(t *testing.T) {
	token := Token{KeyID: "op-dawson", Secret: "s3cr3t-value"}
	now := time.UnixMilli(1794470400000)

	t.Run("hmac accepts a signed request", func(t *testing.T) {
		authenticator := CredentialAuthenticator{Mode: ModeHMAC, Verifier: newTestVerifier(t, token, now)}
		req := httptest.NewRequest("POST", "/api/v1/commands", strings.NewReader(`{"a":1}`))
		signature := signAt(t, token, now, func(ts int64, nonce string) string {
			return CanonicalHTTPRequest("POST", "/api/v1/commands", []byte(`{"a":1}`), ts, nonce)
		})
		req.Header.Set("Authorization", signature.Header())
		identity, ok := authenticator.Authenticate(req)
		if !ok || identity != "operator" {
			t.Fatalf("identity=%q ok=%v, want operator true", identity, ok)
		}
		if keyID, ok := CredentialKeyID(req.Context()); !ok || keyID != token.KeyID {
			t.Fatalf("key_id=%q ok=%v, want %q true", keyID, ok, token.KeyID)
		}
	})

	t.Run("hmac restores the body for the handler", func(t *testing.T) {
		authenticator := CredentialAuthenticator{Mode: ModeHMAC, Verifier: newTestVerifier(t, token, now)}
		const body = `{"a":1}`
		req := httptest.NewRequest("POST", "/api/v1/commands", strings.NewReader(body))
		signature := signAt(t, token, now, func(ts int64, nonce string) string {
			return CanonicalHTTPRequest("POST", "/api/v1/commands", []byte(body), ts, nonce)
		})
		req.Header.Set("Authorization", signature.Header())
		if _, ok := authenticator.Authenticate(req); !ok {
			t.Fatal("signed request was refused")
		}
		restored, err := io.ReadAll(req.Body)
		if err != nil {
			t.Fatal(err)
		}
		if string(restored) != body {
			t.Fatalf("restored body=%q, want %q", restored, body)
		}
	})

	t.Run("bearer accepts a plaintext credential", func(t *testing.T) {
		authenticator := CredentialAuthenticator{Mode: ModeBearer, Bearer: BearerAuthenticator{Token: "plain"}}
		req := httptest.NewRequest("GET", "/api/v1/endpoints", nil)
		req.Header.Set("Authorization", "Bearer plain")
		if identity, ok := authenticator.Authenticate(req); !ok || identity != "operator" {
			t.Fatalf("identity=%q ok=%v", identity, ok)
		}
	})

	t.Run("empty mode selects hmac", func(t *testing.T) {
		authenticator := CredentialAuthenticator{Verifier: newTestVerifier(t, token, now)}
		req := httptest.NewRequest("GET", "/api/v1/endpoints", nil)
		req.Header.Set("Authorization", "Bearer plain")
		if _, ok := authenticator.Authenticate(req); ok {
			t.Fatal("a plaintext credential was accepted while hmac is the default")
		}
	})
}

// TestCredentialAuthenticatorNeverFallsBack proves the two modes are exclusive.
//
// A fallback would let an attacker downgrade a signed deployment by omitting the
// signature, so the refusal has to be absolute rather than "try the other mode".
func TestCredentialAuthenticatorNeverFallsBack(t *testing.T) {
	token := Token{KeyID: "op-dawson", Secret: "s3cr3t-value"}
	now := time.UnixMilli(1794470400000)

	t.Run("hmac mode refuses a valid bearer credential", func(t *testing.T) {
		authenticator := CredentialAuthenticator{
			Mode:     ModeHMAC,
			Bearer:   BearerAuthenticator{Token: "plain"},
			Verifier: newTestVerifier(t, token, now),
		}
		req := httptest.NewRequest("GET", "/api/v1/endpoints", nil)
		req.Header.Set("Authorization", "Bearer plain")
		if _, ok := authenticator.Authenticate(req); ok {
			t.Fatal("hmac mode accepted a bearer credential")
		}
	})

	t.Run("bearer mode refuses a valid signature", func(t *testing.T) {
		authenticator := CredentialAuthenticator{
			Mode:     ModeBearer,
			Bearer:   BearerAuthenticator{Token: "plain"},
			Verifier: newTestVerifier(t, token, now),
		}
		req := httptest.NewRequest("GET", "/api/v1/endpoints", nil)
		signature := signAt(t, token, now, func(ts int64, nonce string) string {
			return CanonicalHTTPRequest("GET", "/api/v1/endpoints", nil, ts, nonce)
		})
		req.Header.Set("Authorization", signature.Header())
		if _, ok := authenticator.Authenticate(req); ok {
			t.Fatal("bearer mode accepted a signature")
		}
	})

	t.Run("unknown mode refuses everything", func(t *testing.T) {
		authenticator := CredentialAuthenticator{
			Mode:     AuthMode("digest"),
			Bearer:   BearerAuthenticator{Token: "plain"},
			Verifier: newTestVerifier(t, token, now),
		}
		req := httptest.NewRequest("GET", "/api/v1/endpoints", nil)
		req.Header.Set("Authorization", "Bearer plain")
		if _, ok := authenticator.Authenticate(req); ok {
			t.Fatal("an unknown mode authenticated a request")
		}
	})
}

func TestCredentialAuthenticatorRejectsTamperedRequest(t *testing.T) {
	token := Token{KeyID: "op-dawson", Secret: "s3cr3t-value"}
	now := time.UnixMilli(1794470400000)
	authenticator := CredentialAuthenticator{Mode: ModeHMAC, Verifier: newTestVerifier(t, token, now)}

	tests := []struct {
		name        string
		signedPath  string
		signedBody  string
		requestPath string
		requestBody string
	}{
		{name: "different body", signedPath: "/api/v1/commands", signedBody: `{"a":1}`, requestPath: "/api/v1/commands", requestBody: `{"a":2}`},
		{name: "different path", signedPath: "/api/v1/endpoints", signedBody: "", requestPath: "/api/v1/commands", requestBody: ""},
		{name: "different query", signedPath: "/api/v1/output?session=a", signedBody: "", requestPath: "/api/v1/output?session=b", requestBody: ""},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			signature := signAt(t, token, now, func(ts int64, nonce string) string {
				return CanonicalHTTPRequest("POST", test.signedPath, []byte(test.signedBody), ts, nonce)
			})
			req := httptest.NewRequest("POST", test.requestPath, strings.NewReader(test.requestBody))
			req.Header.Set("Authorization", signature.Header())
			if _, ok := authenticator.Authenticate(req); ok {
				t.Fatalf("a tampered request was accepted: signed=%q sent=%q", test.signedPath, test.requestPath)
			}
		})
	}
}

func TestCredentialAuthenticatorRejectsMalformedHeader(t *testing.T) {
	token := Token{KeyID: "op-dawson", Secret: "s3cr3t-value"}
	now := time.UnixMilli(1794470400000)
	authenticator := CredentialAuthenticator{Mode: ModeHMAC, Verifier: newTestVerifier(t, token, now)}

	headers := []string{
		"",
		"Bearer plain",
		"AC-HMAC-SHA256",
		"AC-HMAC-SHA256 key_id=op-dawson",
		"AC-HMAC-SHA256 key_id=op-dawson, ts=0, nonce=aa, sig=bb",
		"AC-HMAC-SHA256 key_id=op-dawson, ts=1794470400000, nonce=zz, sig=bb",
		"AC-HMAC-SHA256 key_id=op-dawson, ts=1794470400000, nonce=aa, sig=bb, extra=1",
	}
	for _, header := range headers {
		req := httptest.NewRequest("GET", "/api/v1/endpoints", nil)
		if header != "" {
			req.Header.Set("Authorization", header)
		}
		if _, ok := authenticator.Authenticate(req); ok {
			t.Fatalf("malformed header was accepted: %q", header)
		}
	}
}

func TestCredentialAuthenticatorRequiresVerifier(t *testing.T) {
	authenticator := CredentialAuthenticator{Mode: ModeHMAC}
	req := httptest.NewRequest("GET", "/api/v1/endpoints", nil)
	req.Header.Set("Authorization", "AC-HMAC-SHA256 key_id=a, ts=1, nonce=aa, sig=bb")
	if _, ok := authenticator.Authenticate(req); ok {
		t.Fatal("a verifier-less authenticator accepted a request")
	}
}

func TestBearerAuthenticatorUsesConstantTimeComparison(t *testing.T) {
	// A prefix of the real token must not be accepted, and the full token must be.
	// The comparison itself is constant time; this test pins the accept/reject
	// boundary so a future rewrite cannot reintroduce a prefix match.
	authenticator := BearerAuthenticator{Token: "secret-token"}
	for _, candidate := range []string{"secret-toke", "secret-tokenx", "secret", ""} {
		req := httptest.NewRequest("GET", "/", nil)
		req.Header.Set("Authorization", "Bearer "+candidate)
		if _, ok := authenticator.Authenticate(req); ok {
			t.Fatalf("partial token %q was accepted", candidate)
		}
	}
	req := httptest.NewRequest("GET", "/", nil)
	req.Header.Set("Authorization", "Bearer secret-token")
	if _, ok := authenticator.Authenticate(req); !ok {
		t.Fatal("the exact token was refused")
	}
}

func TestCredentialKeyIDContext(t *testing.T) {
	if keyID, ok := CredentialKeyID(t.Context()); ok || keyID != "" {
		t.Fatalf("background context returned key_id=%q ok=%v", keyID, ok)
	}
	ctx := WithCredentialKeyID(t.Context(), "op-dawson")
	if keyID, ok := CredentialKeyID(ctx); !ok || keyID != "op-dawson" {
		t.Fatalf("key_id=%q ok=%v", keyID, ok)
	}
	ctx = WithCredentialKeyID(ctx, "")
	if keyID, ok := CredentialKeyID(ctx); ok || keyID != "" {
		t.Fatalf("empty key_id returned key_id=%q ok=%v", keyID, ok)
	}
}
