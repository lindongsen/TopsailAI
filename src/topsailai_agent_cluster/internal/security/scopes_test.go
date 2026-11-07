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

func TestAuthorizeOperation(t *testing.T) {
	tests := []struct {
		name       string
		scopes     ScopeSet
		operation  string
		permission string
		declared   bool
		wantErr    bool
	}{
		{
			name:       "unrestricted credential holds declared permission",
			scopes:     NewScopeSet(),
			operation:  "ctl.get_session_messages",
			permission: ScopeControl,
			declared:   true,
		},
		{
			name:       "restricted credential holds declared permission",
			scopes:     NewScopeSet(ScopeControl),
			operation:  "ctl.get_session_messages",
			permission: ScopeControl,
			declared:   true,
		},
		{
			name:       "restricted credential lacks declared permission",
			scopes:     NewScopeSet(ScopeView),
			operation:  "ctl.get_session_messages",
			permission: ScopeControl,
			declared:   true,
			wantErr:    true,
		},
		{
			name:      "control family without declaration is rejected",
			scopes:    NewScopeSet(),
			operation: "ctl.heartbeat",
			wantErr:   true,
		},
		{
			name:       "control family declaring no permission is rejected",
			scopes:     NewScopeSet(ScopeControl),
			operation:  "ctl.heartbeat",
			permission: "",
			declared:   true,
			wantErr:    true,
		},
		{
			name:      "non control operation without declaration keeps existing behaviour",
			scopes:    NewScopeSet(ScopeView),
			operation: "message.send",
		},
		{
			name:       "non control operation with declared permission is enforced",
			scopes:     NewScopeSet(ScopeView),
			operation:  "message.send",
			permission: ScopeSendMessage,
			declared:   true,
			wantErr:    true,
		},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			err := AuthorizeOperation(test.scopes, test.operation, test.permission, test.declared)
			if (err != nil) != test.wantErr {
				t.Fatalf("err=%v, wantErr=%v", err, test.wantErr)
			}
		})
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
