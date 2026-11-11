package server

import (
	"context"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/channel"
	"topsailai_agent_cluster/internal/protocol"
	"topsailai_agent_cluster/internal/security"
	serverstorage "topsailai_agent_cluster/internal/storage/server"
)

// newOutputScopeStore opens a temporary Server store, so a reachability test can
// distinguish an unregistered endpoint from a registered one with no connection.
func newOutputScopeStore(t *testing.T) *serverstorage.Store {
	t.Helper()
	store, err := serverstorage.Open(context.Background(), filepath.Join(t.TempDir(), "server.db"))
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { store.Close() })
	return store
}

// scopedOutputRequester records whether the transport was reached, so a test can
// prove a request was forwarded rather than refused.
type scopedOutputRequester struct {
	snapshotSeen bool
	followSeen   bool
	// token records the Endpoint token the Server forwarded, so a test can prove
	// the credential crosses the Server unchanged instead of being dropped.
	token string
}

func (s *scopedOutputRequester) RequestOutput(ctx context.Context, _ string, _ protocol.OutputSnapshotRequest) (protocol.OutputSnapshotResponse, error) {
	s.snapshotSeen = true
	s.token = security.EndpointToken(ctx)
	return protocol.OutputSnapshotResponse{Data: "line\n", ObservedAtMS: 1}, nil
}

func (s *scopedOutputRequester) RequestFollow(ctx context.Context, _ string, _ protocol.OutputFollowRequest) (<-chan channel.FollowEvent, error) {
	s.followSeen = true
	s.token = security.EndpointToken(ctx)
	events := make(chan channel.FollowEvent, 1)
	events <- channel.FollowEvent{End: &protocol.OutputEnd{}}
	close(events)
	return events, nil
}

// scopedOutputHandler builds a handler whose credential holds exactly the given
// scopes. An empty list is the unrestricted single-administrator deployment.
//
// The transport is an interface rather than the recording double, so a test can
// substitute a transport that answers with a refusal code.
func scopedOutputHandler(scopes []string, output OutputRequester) *Handler {
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

// TestOutputRoutesForwardCredentialWithoutReadOutput proves the Server no longer
// refuses an output read on permission grounds.
//
// Authorization belongs to the Endpoint that owns the machine. A Server-side
// refusal would be a second authority the Endpoint could not revoke, so a
// credential that lacks read_output must still reach the transport: the Endpoint
// decides, and it answers with policy_denied.
func TestOutputRoutesForwardCredentialWithoutReadOutput(t *testing.T) {
	paths := []string{
		"/api/v1/output?endpoint_id=e1&resource_id=res_1&provider_generation=g1",
		"/api/v1/output/follow?endpoint_id=e1&resource_id=res_1&provider_generation=g1",
	}
	for _, path := range paths {
		t.Run(path, func(t *testing.T) {
			output := &scopedOutputRequester{}
			rec := callScopedOutput(t, scopedOutputHandler([]string{security.ScopeView}, output), path)
			if rec.Code == http.StatusForbidden {
				t.Fatalf("the Server refused an output read on permission grounds: %s", rec.Body.String())
			}
			if !output.snapshotSeen && !output.followSeen {
				t.Fatalf("the request never reached the transport: %s", rec.Body.String())
			}
		})
	}
}

// TestOutputRoutesForwardEndpointToken proves the Endpoint token crosses the
// Server unchanged.
//
// The token is the Endpoint's credential, so the Server must carry it without
// interpreting it. Dropping it would make every read fail closed at the Endpoint,
// and rewriting it would let the Server choose which policy applies.
func TestOutputRoutesForwardEndpointToken(t *testing.T) {
	paths := []string{
		"/api/v1/output?endpoint_id=e1&resource_id=res_1&provider_generation=g1",
		"/api/v1/output/follow?endpoint_id=e1&resource_id=res_1&provider_generation=g1",
	}
	for _, path := range paths {
		t.Run(path, func(t *testing.T) {
			output := &scopedOutputRequester{}
			req := httptest.NewRequest(http.MethodGet, path, nil)
			req.Header.Set("Authorization", "Bearer secret")
			req.Header.Set(endpointTokenHeader, "endpoint-secret")
			rec := httptest.NewRecorder()
			scopedOutputHandler(nil, output).ServeHTTP(rec, req)
			if output.token != "endpoint-secret" {
				t.Fatalf("forwarded token=%q want endpoint-secret", output.token)
			}
		})
	}
}

// TestOutputRoutesForwardAbsentEndpointToken proves an absent token stays absent.
//
// A missing credential must never be replaced by a default, because a default
// would be a credential nobody provisioned. The Endpoint refuses an empty token,
// so forwarding it unchanged is what makes the refusal possible.
func TestOutputRoutesForwardAbsentEndpointToken(t *testing.T) {
	output := &scopedOutputRequester{}
	rec := callScopedOutput(t, scopedOutputHandler(nil, output), "/api/v1/output?endpoint_id=e1&resource_id=res_1")
	if rec.Code == http.StatusForbidden {
		t.Fatalf("an absent Endpoint token was refused by the Server: %s", rec.Body.String())
	}
	if output.token != "" {
		t.Fatalf("forwarded token=%q want empty", output.token)
	}
}

// TestOutputRoutesAdmitUnrestrictedCredential proves the default deployment still
// works, so the removed check did not narrow the single-administrator case.
func TestOutputRoutesAdmitUnrestrictedCredential(t *testing.T) {
	output := &scopedOutputRequester{}
	rec := callScopedOutput(t, scopedOutputHandler(nil, output), "/api/v1/output?endpoint_id=e1&resource_id=res_1")
	if rec.Code != http.StatusOK {
		t.Fatalf("status=%d body=%s want 200", rec.Code, rec.Body.String())
	}
	if !output.snapshotSeen {
		t.Fatal("the transport was not reached")
	}
}

// TestOutputRoutesStillRequireAuthentication proves removing the permission check
// did not remove authentication.
//
// Reachability and authorization are different questions. The Server still
// decides whether a caller may talk to the cluster at all; it no longer decides
// what that caller may do on a machine.
func TestOutputRoutesStillRequireAuthentication(t *testing.T) {
	output := &scopedOutputRequester{}
	req := httptest.NewRequest(http.MethodGet, "/api/v1/output?endpoint_id=e1&resource_id=res_1", nil)
	req.Header.Set("Authorization", "Bearer wrong")
	rec := httptest.NewRecorder()
	scopedOutputHandler(nil, output).ServeHTTP(rec, req)
	if rec.Code != http.StatusUnauthorized {
		t.Fatalf("status=%d body=%s want 401", rec.Code, rec.Body.String())
	}
	if output.snapshotSeen {
		t.Fatal("an unauthenticated request reached the transport")
	}
}

// TestOutputRoutesReportUnknownEndpointAsNotFound proves a typo is not reported
// as an outage.
//
// The Server verifies that the target exists, which is a reachability question.
// Reporting an unregistered identifier as offline would tell an operator to
// investigate a machine that was never registered.
func TestOutputRoutesReportUnknownEndpointAsNotFound(t *testing.T) {
	store := newOutputScopeStore(t)
	output := &scopedOutputRequester{}
	h := &Handler{
		Store:         store,
		Authenticator: security.BearerAuthenticator{Token: "secret"},
		Output:        output,
	}
	rec := callScopedOutput(t, h, "/api/v1/output?endpoint_id=missing&resource_id=res_1")
	if rec.Code != http.StatusNotFound {
		t.Fatalf("status=%d body=%s want 404", rec.Code, rec.Body.String())
	}
	if !strings.Contains(rec.Body.String(), "endpoint_not_found") {
		t.Fatalf("body=%s want code endpoint_not_found", rec.Body.String())
	}
	if output.snapshotSeen {
		t.Fatal("an unknown endpoint reached the transport")
	}
}

// refusedOutputRequester answers every output read with the Endpoint refusal
// code and no Go error, which is how a refusal actually arrives.
//
// A refusal is a successful answer to the request: the Endpoint decided, and it
// decided no. Modelling it as an error would let the handler classify it as an
// outage, which is the defect these tests guard.
type refusedOutputRequester struct{ scopedOutputRequester }

func (r *refusedOutputRequester) RequestOutput(context.Context, string, protocol.OutputSnapshotRequest) (protocol.OutputSnapshotResponse, error) {
	return protocol.OutputSnapshotResponse{ErrorCode: protocol.PolicyDenied}, nil
}

// TestOutputSnapshotReportsRefusalAsForbidden proves an Endpoint refusal is not
// reported as a successful empty snapshot.
//
// The Endpoint answered, so the request did not fail. Reporting the refusal as a
// 200 with an empty body would hand the operator a blank panel and no reason,
// and reporting it as an outage would send them to investigate a provider that
// was never invoked.
func TestOutputSnapshotReportsRefusalAsForbidden(t *testing.T) {
	rec := callScopedOutput(t, scopedOutputHandler(nil, &refusedOutputRequester{}), "/api/v1/output?endpoint_id=e1&resource_id=res_1")
	if rec.Code != http.StatusForbidden {
		t.Fatalf("status=%d body=%s want 403", rec.Code, rec.Body.String())
	}
	if !strings.Contains(rec.Body.String(), `"`+protocol.PolicyDenied+`"`) {
		t.Fatalf("body=%s want code %q", rec.Body.String(), protocol.PolicyDenied)
	}
}

// TestOutputRoutesReportRegisteredEndpointAsUnavailable proves a registered
// endpoint with no live connection is reported as an outage rather than as a
// missing registration.
func TestOutputRoutesReportRegisteredEndpointAsUnavailable(t *testing.T) {
	store := newOutputScopeStore(t)
	if err := store.UpsertEndpoint(context.Background(), protocol.Endpoint{EndpointID: "e1", InstanceID: "i1", DisplayName: "one", ConnectionState: "offline", ObservedAtMS: 1, CapabilityRevision: "c1"}, 1); err != nil {
		t.Fatal(err)
	}
	output := &scopedOutputRequester{}
	h := &Handler{
		Store:         store,
		Authenticator: security.BearerAuthenticator{Token: "secret"},
		Output:        output,
	}
	rec := callScopedOutput(t, h, "/api/v1/output?endpoint_id=e1&resource_id=res_1")
	if rec.Code == http.StatusNotFound {
		t.Fatalf("a registered endpoint was reported as not found: %s", rec.Body.String())
	}
}
