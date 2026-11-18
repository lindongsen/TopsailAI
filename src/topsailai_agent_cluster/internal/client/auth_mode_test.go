package client

import (
	"context"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"topsailai_agent_cluster/internal/security"
)

// TestHMACModeSignsTheServerCredential verifies the client produces a signature
// the Server-side verifier accepts.
//
// The assertion runs the real verifier rather than inspecting the header shape,
// because a header that merely looks like a signature proves nothing about
// whether the signed string matches the one the Server rebuilds. A mismatch
// would be reported to the operator as an authentication failure, which points
// at the credential instead of at the grammar.
func TestHMACModeSignsTheServerCredential(t *testing.T) {
	token, err := security.ParseToken("op-dawson.s3cr3t-value")
	if err != nil {
		t.Fatalf("ParseToken: %v", err)
	}
	verifier := security.NewVerifier(map[string]security.Token{token.KeyID: token}, time.Minute)

	var verified bool
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		body, readErr := io.ReadAll(r.Body)
		if readErr != nil {
			t.Errorf("read body: %v", readErr)
		}
		signature, parseErr := security.ParseSignatureHeader(r.Header.Get("Authorization"))
		if parseErr != nil {
			t.Errorf("parse signature header: %v", parseErr)
			http.Error(w, `{"message":"unauthorized"}`, http.StatusUnauthorized)
			return
		}
		message := security.CanonicalHTTPRequest(r.Method, r.URL.RequestURI(), body, signature.TimestampMS, signature.Nonce)
		if verifyErr := verifier.Verify(message, signature); verifyErr != nil {
			t.Errorf("verify: %v", verifyErr)
			http.Error(w, `{"message":"unauthorized"}`, http.StatusUnauthorized)
			return
		}
		verified = true
		w.Header().Set("Content-Type", "application/json")
		_, _ = fmt.Fprint(w, `{"code":0,"message":"ok","data":[]}`)
	}))
	defer server.Close()

	api := NewAPIClient(server.URL, "op-dawson.s3cr3t-value")
	api.AuthMode = security.ModeHMAC
	if _, err := api.ListEndpoints(context.Background()); err != nil {
		t.Fatalf("ListEndpoints: %v", err)
	}
	if !verified {
		t.Fatal("the Server verifier never accepted the signature")
	}
}

// TestHMACModeRefusesATokenWithoutAKeyID verifies a credential that cannot be
// signed is refused locally.
//
// HMAC mode needs the key identifier to tell the verifier which secret to use,
// so a token without one cannot produce a signature at all. Sending it unsigned
// would be refused by the Server with a generic authentication failure, which
// describes the token value instead of its format.
func TestHMACModeRefusesATokenWithoutAKeyID(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		t.Error("a request was sent for a credential that cannot be signed")
		http.Error(w, `{"message":"unauthorized"}`, http.StatusUnauthorized)
	}))
	defer server.Close()

	api := NewAPIClient(server.URL, "plain-token-without-a-dot")
	api.AuthMode = security.ModeHMAC
	_, err := api.ListEndpoints(context.Background())
	if err == nil {
		t.Fatal("a token without a key identifier was accepted in hmac mode")
	}
	if !strings.Contains(err.Error(), "key_id.secret") {
		t.Fatalf("error does not name the required form: %v", err)
	}
}

// TestBearerModeSendsNoSignature verifies the two modes are exclusive.
//
// A request carrying both a bearer token and a signature would leave the
// operator unable to tell which credential the Server actually accepted, and a
// Server configured for one mode refuses the other.
func TestBearerModeSendsNoSignature(t *testing.T) {
	var authorization string
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		authorization = r.Header.Get("Authorization")
		w.Header().Set("Content-Type", "application/json")
		_, _ = fmt.Fprint(w, `{"code":0,"message":"ok","data":[]}`)
	}))
	defer server.Close()

	api := NewAPIClient(server.URL, "plain-token")
	api.AuthMode = security.ModeBearer
	if _, err := api.ListEndpoints(context.Background()); err != nil {
		t.Fatalf("ListEndpoints: %v", err)
	}
	if authorization != "Bearer plain-token" {
		t.Fatalf("Authorization=%q, want the bearer form", authorization)
	}
	if strings.Contains(authorization, security.HMACScheme) {
		t.Fatalf("bearer mode also sent a signature: %q", authorization)
	}
}

// TestUnknownModeRefusesLocally verifies an unrecognised mode never falls back.
//
// Falling back to either mode would present a credential in a scheme the
// operator did not select, and the Server's refusal would then describe the
// wrong problem.
func TestUnknownModeRefusesLocally(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		t.Error("a request was sent in an unrecognised authentication mode")
		http.Error(w, `{"message":"unauthorized"}`, http.StatusUnauthorized)
	}))
	defer server.Close()

	api := NewAPIClient(server.URL, "op-dawson.s3cr3t-value")
	api.AuthMode = security.AuthMode("digest")
	_, err := api.ListEndpoints(context.Background())
	if err == nil {
		t.Fatal("an unrecognised authentication mode was accepted")
	}
	if !strings.Contains(err.Error(), "unsupported authentication mode") {
		t.Fatalf("error does not name the unsupported mode: %v", err)
	}
}
