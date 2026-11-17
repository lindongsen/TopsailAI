package genericcli

import (
	"context"
	"errors"
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
	"topsailai_agent_cluster/internal/providercli"
)

// clusterResourceIDForMetricsBatch is a value with the exact shape the Endpoint
// mints. It is built from the shared prefix rather than written as a literal, so a
// change to the prefix cannot leave this fixture testing a shape that no longer
// exists.
func clusterResourceIDForMetricsBatch() string {
	return protocol.ClusterResourceIDPrefix + strings.Repeat("0123456789abcdef", 2)
}

// metricsBatchQueryAdapter advertises the batch query and fails the test if the
// provider is invoked for anything but describe.
//
// The assertion is the point of the helper: a refusal that happened after the
// provider process started would still return an error, so only the invocation
// count proves the request was refused at the contract boundary.
func metricsBatchQueryAdapter(t *testing.T) *Adapter {
	t.Helper()
	provider := newFakeProvider(t)
	provider.invoke = func(request providercli.Request) (providercli.Response, error) {
		if request.Function == providercli.FunctionDescribe {
			response := describeResponseWithFunctions(request, providercli.FunctionQuery)
			for _, query := range providercli.StandardQueries() {
				response.Descriptor.Queries = append(response.Descriptor.Queries, providercli.NamedContract{Name: query.Name, Version: query.Version})
			}
			return response, nil
		}
		t.Fatalf("the provider was invoked for a request that should have been refused at the contract boundary: %s", request.Function)
		return providercli.Response{}, nil
	}
	return mustAdapter(t, provider)
}

// TestMetricsBatchRejectsAClusterResourceIDWithACallerErrorCode proves the real
// adapter path reports a caller error when a Cluster resource ID reaches a batch
// member.
//
// The single-session read puts its session identifier in the target, where the
// contract rejects a Cluster resource ID. The batch read puts its members in the
// payload, so the same value took a different validation path and was accepted.
// The provider then could not resolve it and silently omitted the member, which the
// caller renders as an unmeasured session: a caller error presented as a provider
// observation.
//
// This test drives the real MetricsBatch method so the wrapping shape is the
// production one rather than a stand-in.
func TestMetricsBatchRejectsAClusterResourceIDWithACallerErrorCode(t *testing.T) {
	clusterID := clusterResourceIDForMetricsBatch()
	if !protocol.IsClusterResourceID(clusterID) {
		t.Fatalf("the fixture %q does not have the Cluster resource ID shape, so this guard checked nothing", clusterID)
	}
	binding := metricsBatchQueryAdapter(t)
	_, err := binding.MetricsBatch(context.Background(), protocol.SessionMetricsBatchQuery{
		ProviderSessionIDs: []string{clusterID},
	})
	if err == nil {
		t.Fatal("a Cluster resource ID was accepted where a provider session ID belongs")
	}
	var coded interface{ ErrorCode() string }
	if !errors.As(err, &coded) {
		t.Fatalf("the adapter returned an error no caller can classify: %v", err)
	}
	if got := coded.ErrorCode(); got != protocol.InvalidTarget {
		t.Fatalf("adapter error code=%q want=%q", got, protocol.InvalidTarget)
	}
}

// TestMetricsBatchRejectsOneClusterResourceIDAmongValidMembers proves a single bad
// member refuses the whole request rather than being dropped.
//
// Dropping it would be the tempting local behaviour, because the batch result
// already tolerates an absent member. That tolerance exists for a session the
// provider could not measure, not for a request the caller wrote incorrectly, and
// collapsing the two would make the caller's mistake invisible.
func TestMetricsBatchRejectsOneClusterResourceIDAmongValidMembers(t *testing.T) {
	clusterID := clusterResourceIDForMetricsBatch()
	binding := metricsBatchQueryAdapter(t)
	_, err := binding.MetricsBatch(context.Background(), protocol.SessionMetricsBatchQuery{
		ProviderSessionIDs: []string{"session:stable", clusterID},
	})
	if err == nil {
		t.Fatal("a Cluster resource ID was accepted when it was one member of a set")
	}
	var coded interface{ ErrorCode() string }
	if !errors.As(err, &coded) {
		t.Fatalf("the adapter returned an error no caller can classify: %v", err)
	}
	if got := coded.ErrorCode(); got != protocol.InvalidTarget {
		t.Fatalf("adapter error code=%q want=%q", got, protocol.InvalidTarget)
	}
}

// TestMetricsBatchAcceptsProviderSessionIDs proves the guard did not make the
// surface unusable.
//
// A rejection applied to every member would pass the two tests above while breaking
// the batch read entirely, so the accepting path needs its own assertion on the same
// real method.
func TestMetricsBatchAcceptsProviderSessionIDs(t *testing.T) {
	provider := newFakeProvider(t)
	provider.invoke = func(request providercli.Request) (providercli.Response, error) {
		if request.Function == providercli.FunctionDescribe {
			response := describeResponseWithFunctions(request, providercli.FunctionQuery)
			for _, query := range providercli.StandardQueries() {
				response.Descriptor.Queries = append(response.Descriptor.Queries, providercli.NamedContract{Name: query.Name, Version: query.Version})
			}
			return response, nil
		}
		return providercli.Response{
			Version:     request.Version,
			RequestID:   request.RequestID,
			OK:          true,
			QueryResult: []byte(`{"results":[{"provider_session_id":"session:stable","messages":{"inbound":2,"outbound":3},"observed_at_ms":1000}],"observed_at_ms":1000}`),
		}, nil
	}
	binding := mustAdapter(t, provider)
	result, err := binding.MetricsBatch(context.Background(), protocol.SessionMetricsBatchQuery{
		ProviderSessionIDs: []string{"session:stable"},
	})
	if err != nil {
		t.Fatalf("a legitimate provider session ID was rejected: %v", err)
	}
	if result.ErrorCode != "" {
		t.Fatalf("a legitimate read reported error code %q", result.ErrorCode)
	}
	if len(result.Results) != 1 {
		t.Fatalf("results=%d want=1", len(result.Results))
	}
	if result.Results[0].Messages.Inbound != 2 || result.Results[0].Messages.Outbound != 3 {
		t.Fatalf("counts=%+v want inbound=2 outbound=3", result.Results[0].Messages)
	}
}
