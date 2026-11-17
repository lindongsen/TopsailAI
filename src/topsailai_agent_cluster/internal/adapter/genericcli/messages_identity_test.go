package genericcli

import (
	"context"
	"errors"
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
	"topsailai_agent_cluster/internal/providercli"
)

// clusterResourceIDForMessages is a value with the exact shape the Endpoint mints.
// It is built from the shared prefix rather than written as a literal, so a change
// to the prefix cannot leave this fixture testing a shape that no longer exists.
func clusterResourceIDForMessages() string {
	return protocol.ClusterResourceIDPrefix + strings.Repeat("0123456789abcdef", 2)
}

// TestMessagesRejectsAClusterResourceIDWithACallerErrorCode proves the real adapter
// path reports a caller error when a Cluster resource ID reaches a provider key.
//
// The rejection happens inside the contract validation, which the adapter wraps with
// its own context before returning. A classification that only inspected the
// outermost error would therefore miss it and fall back to a provider failure, which
// is exactly the reported defect. This test drives the real Messages method so the
// wrapping shape is the production one rather than a stand-in.
func TestMessagesRejectsAClusterResourceIDWithACallerErrorCode(t *testing.T) {
	clusterID := clusterResourceIDForMessages()
	if !protocol.IsClusterResourceID(clusterID) {
		t.Fatalf("the fixture %q does not have the Cluster resource ID shape, so this guard checked nothing", clusterID)
	}
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
	binding := mustAdapter(t, provider)
	_, err := binding.Messages(context.Background(), protocol.MessagesQuery{ProviderSessionID: clusterID})
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
	if len(provider.requests) != 1 {
		t.Fatalf("provider invocations=%d want=1 (describe only), so the refusal did not happen before the provider call", len(provider.requests))
	}
}

// TestMessagesAcceptsAProviderSessionID proves the guard did not make the surface
// unusable.
//
// A rejection applied to every value would pass the test above while breaking the
// command, so the accepting path needs its own assertion on the same real method.
func TestMessagesAcceptsAProviderSessionID(t *testing.T) {
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
			QueryResult: []byte(`{"provider_session_id":"session:stable","messages":[],"message_count":0,"observed_at_ms":1000}`),
		}, nil
	}
	binding := mustAdapter(t, provider)
	result, err := binding.Messages(context.Background(), protocol.MessagesQuery{ProviderSessionID: "session:stable"})
	if err != nil {
		t.Fatalf("a legitimate provider session ID was rejected: %v", err)
	}
	if result.ErrorCode != "" {
		t.Fatalf("a legitimate read reported error code %q", result.ErrorCode)
	}
}
