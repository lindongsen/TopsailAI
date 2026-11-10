package server

import (
	"context"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/channel"
	"topsailai_agent_cluster/internal/protocol"
	"topsailai_agent_cluster/internal/security"
)

// scopedOutputRequester records whether the transport was reached, so a test can
// prove a rejected request never left the Server.
type scopedOutputRequester struct {
	snapshotSeen bool
	followSeen   bool
}

func (s *scopedOutputRequester) RequestOutput(context.Context, string, protocol.OutputSnapshotRequest) (protocol.OutputSnapshotResponse, error) {
	s.snapshotSeen = true
	return protocol.OutputSnapshotResponse{Data: "line\n", ObservedAtMS: 1}, nil
}

func (s *scopedOutputRequester) RequestFollow(context.Context, string, protocol.OutputFollowRequest) (<-chan channel.FollowEvent, error) {
	s.followSeen = true
	events := make(chan channel.FollowEvent, 1)
	events <- channel.FollowEvent{End: &protocol.OutputEnd{}}
	close(events)
	return events, nil
}

// scopedOutputHandler builds a handler whose credential holds exactly the given
// scopes. An empty list is the unrestricted single-administrator deployment.
func scopedOutputHandler(scopes []string, output *scopedOutputRequester) *Handler {
	return &Handler{
		Authenticator: security.BearerAuthenticator{Token: "secret", Scopes: security.NewScopeSet(scopes...)},
		Output:        output,
	}
}

// callScopedOutput issues one authenticated request against an output route.
func callScopedOutput(t *testing.T, h *Handler, path string) *httptest.ResponseRecorder {
	t.Helper()
	req := httptest.NewRequest(http.MethodGet, path, nil)
	req.Header.Set("Authorization", "Bearer secret")
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)
	return rec
}

// TestOutputRoutesRejectCredentialWithoutReadOutput verifies a credential that
// lacks read_output is refused on both output routes, and that the refusal
// happens before the transport is consulted.
func TestOutputRoutesRejectCredentialWithoutReadOutput(t *testing.T) {
	paths := []string{
		"/api/v1/output?endpoint_id=e1&resource_id=res_1&provider_generation=g1",
		"/api/v1/output/follow?endpoint_id=e1&resource_id=res_1&provider_generation=g1",
	}
	for _, path := range paths {
		t.Run(path, func(t *testing.T) {
			output := &scopedOutputRequester{}
			h := scopedOutputHandler([]string{security.ScopeView}, output)
			rec := callScopedOutput(t, h, path)
			if rec.Code != http.StatusForbidden {
				t.Fatalf("status %d: %s", rec.Code, rec.Body.String())
			}
			if !strings.Contains(rec.Body.String(), "permission_denied") {
				t.Fatalf("body %q", rec.Body.String())
			}
			if !strings.Contains(rec.Body.String(), security.ScopeReadOutput) {
				t.Fatalf("body does not name the missing scope: %q", rec.Body.String())
			}
			if output.snapshotSeen || output.followSeen {
				t.Fatal("a rejected request reached the transport")
			}
		})
	}
}

// TestOutputRoutesAdmitCredentialWithReadOutput verifies a credential holding
// read_output reaches the transport on both routes.
func TestOutputRoutesAdmitCredentialWithReadOutput(t *testing.T) {
	output := &scopedOutputRequester{}
	h := scopedOutputHandler([]string{security.ScopeReadOutput}, output)

	snapshot := callScopedOutput(t, h, "/api/v1/output?endpoint_id=e1&resource_id=res_1&provider_generation=g1")
	if snapshot.Code != http.StatusOK {
		t.Fatalf("snapshot status %d: %s", snapshot.Code, snapshot.Body.String())
	}
	if !output.snapshotSeen {
		t.Fatal("snapshot request did not reach the transport")
	}

	follow := callScopedOutput(t, h, "/api/v1/output/follow?endpoint_id=e1&resource_id=res_1&provider_generation=g1")
	if follow.Code != http.StatusOK {
		t.Fatalf("follow status %d: %s", follow.Code, follow.Body.String())
	}
	if !output.followSeen {
		t.Fatal("follow request did not reach the transport")
	}
}

// TestOutputRoutesAdmitUnrestrictedCredential verifies the single-administrator
// deployment keeps working: an empty scope set holds every permission.
func TestOutputRoutesAdmitUnrestrictedCredential(t *testing.T) {
	output := &scopedOutputRequester{}
	h := scopedOutputHandler(nil, output)
	rec := callScopedOutput(t, h, "/api/v1/output?endpoint_id=e1&resource_id=res_1&provider_generation=g1")
	if rec.Code != http.StatusOK {
		t.Fatalf("status %d: %s", rec.Code, rec.Body.String())
	}
	if !output.snapshotSeen {
		t.Fatal("unrestricted credential did not reach the transport")
	}
}

// TestOutputRoutesRejectBeforeCapabilityProbe verifies the authorization check
// runs before the handler inspects transport capability, so an unauthorized
// caller cannot learn whether streaming is configured.
func TestOutputRoutesRejectBeforeCapabilityProbe(t *testing.T) {
	// A snapshot-only transport would answer "unsupported" on the follow route if
	// the capability probe ran first. The caller must see a permission failure
	// instead, which proves the order.
	h := &Handler{
		Authenticator: security.BearerAuthenticator{Token: "secret", Scopes: security.NewScopeSet(security.ScopeView)},
		Output:        snapshotOnlyRequester{},
	}
	rec := callScopedOutput(t, h, "/api/v1/output/follow?endpoint_id=e1&resource_id=res_1")
	if rec.Code != http.StatusForbidden {
		t.Fatalf("status %d: %s", rec.Code, rec.Body.String())
	}
	if strings.Contains(rec.Body.String(), "unsupported") {
		t.Fatalf("capability was disclosed to an unauthorized caller: %q", rec.Body.String())
	}
}

// TestOutputRoutesRejectBeforeChannelAvailability verifies an unauthorized caller
// cannot distinguish an offline Endpoint from an online one.
func TestOutputRoutesRejectBeforeChannelAvailability(t *testing.T) {
	h := &Handler{
		Authenticator: security.BearerAuthenticator{Token: "secret", Scopes: security.NewScopeSet(security.ScopeView)},
	}
	rec := callScopedOutput(t, h, "/api/v1/output?endpoint_id=e1&resource_id=res_1")
	if rec.Code != http.StatusForbidden {
		t.Fatalf("status %d: %s", rec.Code, rec.Body.String())
	}
	if strings.Contains(rec.Body.String(), "endpoint_offline") {
		t.Fatalf("channel availability was disclosed to an unauthorized caller: %q", rec.Body.String())
	}
}

// TestAuthorizeOutputReadContext verifies the context-only form agrees with the
// handler form, so a future caller cannot drift from the enforced rule.
func TestAuthorizeOutputReadContext(t *testing.T) {
	restricted := security.WithAuthenticatedScopes(context.Background(), security.NewScopeSet(security.ScopeView))
	if err := authorizeOutputReadContext(restricted, operationOutputSnapshot); err == nil {
		t.Fatal("a view-only credential was authorized to read output")
	}
	allowed := security.WithAuthenticatedScopes(context.Background(), security.NewScopeSet(security.ScopeReadOutput))
	if err := authorizeOutputReadContext(allowed, operationOutputFollow); err != nil {
		t.Fatalf("a read_output credential was refused: %v", err)
	}
	unrestricted := security.WithAuthenticatedScopes(context.Background(), security.NewScopeSet())
	if err := authorizeOutputReadContext(unrestricted, operationOutputSnapshot); err != nil {
		t.Fatalf("an unrestricted credential was refused: %v", err)
	}
}
