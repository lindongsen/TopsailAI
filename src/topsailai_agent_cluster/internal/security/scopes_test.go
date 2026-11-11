package security

import (
	"net/http/httptest"
	"testing"
)

func TestAuthenticateRejectsWrongToken(t *testing.T) {
	req := httptest.NewRequest("GET", "/", nil)
	req.Header.Set("Authorization", "Bearer other")
	if _, ok := (BearerAuthenticator{Token: "secret"}).Authenticate(req); ok {
		t.Fatalf("wrong token must not authenticate")
	}
}

func TestAuthenticateAcceptsConfiguredToken(t *testing.T) {
	req := httptest.NewRequest("GET", "/", nil)
	req.Header.Set("Authorization", "Bearer secret")
	identity, ok := (BearerAuthenticator{Token: "secret"}).Authenticate(req)
	if !ok || identity != "operator" {
		t.Fatalf("identity=%q ok=%v", identity, ok)
	}
}
