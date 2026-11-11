package security

import (
	"context"
	"net/http/httptest"
	"testing"
)

func TestNewScopeSetDropsEmptyEntries(t *testing.T) {
	set := NewScopeSet("view", "  ", "", "control")
	if !set.Has("view") || !set.Has("control") {
		t.Fatalf("expected view and control scopes, got %v", set)
	}
	if set.Has("") {
		t.Fatalf("empty scope must not be stored")
	}
	if len(set) != 2 {
		t.Fatalf("expected 2 scopes, got %d", len(set))
	}
}

func TestScopeSetUnrestricted(t *testing.T) {
	if !NewScopeSet().Unrestricted() {
		t.Fatalf("empty scope set must be unrestricted")
	}
	if NewScopeSet("view").Unrestricted() {
		t.Fatalf("configured scope set must be restricted")
	}
}

func TestAuthenticatedScopesRoundTrip(t *testing.T) {
	ctx := WithAuthenticatedScopes(context.Background(), NewScopeSet(ScopeView))
	if !AuthenticatedScopes(ctx).Has(ScopeView) {
		t.Fatalf("expected view scope to survive context round trip")
	}
	if AuthenticatedScopes(context.Background()).Unrestricted() != true {
		t.Fatalf("absent scopes must be unrestricted")
	}
}

func TestAuthenticateScopesReturnsConfiguredScopes(t *testing.T) {
	req := httptest.NewRequest("GET", "/", nil)
	req.Header.Set("Authorization", "Bearer secret")
	identity, scopes, ok := (BearerAuthenticator{Token: "secret", Scopes: NewScopeSet(ScopeView)}).AuthenticateScopes(req)
	if !ok || identity != "operator" {
		t.Fatalf("identity=%q ok=%v", identity, ok)
	}
	if !scopes.Has(ScopeView) || scopes.Unrestricted() {
		t.Fatalf("expected restricted view scope, got %v", scopes)
	}
}

func TestAuthenticateScopesRejectsWrongToken(t *testing.T) {
	req := httptest.NewRequest("GET", "/", nil)
	req.Header.Set("Authorization", "Bearer other")
	if _, _, ok := (BearerAuthenticator{Token: "secret"}).AuthenticateScopes(req); ok {
		t.Fatalf("wrong token must not authenticate")
	}
}
