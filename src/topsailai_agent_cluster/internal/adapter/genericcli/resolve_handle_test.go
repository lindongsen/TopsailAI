package genericcli

import (
	"context"
	"encoding/json"
	"errors"
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/adapter"
	"topsailai_agent_cluster/internal/protocol"
	"topsailai_agent_cluster/internal/providercli"
)

// resolveProvider builds a fake Provider that advertises resolve and answers it
// with the supplied resolution. Every request is recorded for inspection.
func resolveProvider(t *testing.T, resolution *providercli.ResolutionResult) *fakeRunner {
	t.Helper()
	provider := newFakeProvider(t)
	provider.invoke = func(request providercli.Request) (providercli.Response, error) {
		if request.Function == providercli.FunctionDescribe {
			return describeResponseWithFunctions(request, providercli.FunctionResolve), nil
		}
		if request.Function == providercli.FunctionResolve {
			return providercli.Response{Version: request.Version, RequestID: request.RequestID, OK: true, Resolution: resolution}, nil
		}
		return describeResponse(request), nil
	}
	return provider
}

// TestResolveProviderSessionHandleMintsThroughTheMapper proves the adapter
// forwards the handle, takes the key from the Provider and records it through
// the same mapper discovery uses.
func TestResolveProviderSessionHandleMintsThroughTheMapper(t *testing.T) {
	provider := resolveProvider(t, &providercli.ResolutionResult{ProviderResourceKey: "provider-minted-key", ResourceKind: protocol.ResourceSession})
	binding := mustAdapter(t, provider)
	mapping, err := binding.ResolveProviderSessionHandle(context.Background(), "session-abc")
	if err != nil {
		t.Fatalf("resolve handle: %v", err)
	}
	if mapping.ProviderResourceKey != "provider-minted-key" || mapping.ResourceKind != protocol.ResourceSession || mapping.AdapterID != "a" {
		t.Fatalf("mapping = %+v", mapping)
	}
	if mapping.ResourceID != protocol.ResourceSession+"-provider-minted-key" {
		t.Fatalf("resource ID = %q, want the mapper minted identity", mapping.ResourceID)
	}
	var resolveRequest *providercli.Request
	for index := range provider.requests {
		if provider.requests[index].Function == providercli.FunctionResolve {
			resolveRequest = &provider.requests[index]
		}
	}
	if resolveRequest == nil {
		t.Fatal("no resolve request reached the Provider")
	}
	if resolveRequest.Target != nil {
		t.Fatalf("resolve request carried a target: %+v", resolveRequest.Target)
	}
	if resolveRequest.InvocationID != "" {
		t.Fatalf("resolve request carried an invocation ID: %q", resolveRequest.InvocationID)
	}
	var payload map[string]string
	if err := json.Unmarshal(resolveRequest.Payload, &payload); err != nil {
		t.Fatalf("decode resolve payload: %v", err)
	}
	if len(payload) != 1 || payload["handle"] != "session-abc" {
		t.Fatalf("resolve payload = %v, want only the handle", payload)
	}
}

// TestResolveProviderSessionHandleDoesNotBuildTheKeyItself pins the module
// boundary: provider key spelling must never appear in cluster code, so the
// adapter may only forward the handle.
func TestResolveProviderSessionHandleDoesNotBuildTheKeyItself(t *testing.T) {
	provider := resolveProvider(t, &providercli.ResolutionResult{ProviderResourceKey: "provider-minted-key", ResourceKind: protocol.ResourceSession})
	binding := mustAdapter(t, provider)
	if _, err := binding.ResolveProviderSessionHandle(context.Background(), "session-abc"); err != nil {
		t.Fatalf("resolve handle: %v", err)
	}
	for _, request := range provider.requests {
		if request.Function != providercli.FunctionResolve {
			continue
		}
		payload := string(request.Payload)
		for _, spelling := range []string{"session:v1:", "session-row:", "session-history:"} {
			if strings.Contains(payload, spelling) {
				t.Fatalf("resolve payload carries provider key spelling %q: %s", spelling, payload)
			}
		}
	}
}

// TestResolveProviderSessionHandleRejectsAnEmptyHandle proves an empty handle
// never reaches the Provider.
func TestResolveProviderSessionHandleRejectsAnEmptyHandle(t *testing.T) {
	provider := resolveProvider(t, &providercli.ResolutionResult{ProviderResourceKey: "provider-minted-key", ResourceKind: protocol.ResourceSession})
	binding := mustAdapter(t, provider)
	if _, err := binding.ResolveProviderSessionHandle(context.Background(), ""); err == nil {
		t.Fatal("empty handle was accepted")
	}
	for _, request := range provider.requests {
		if request.Function == providercli.FunctionResolve {
			t.Fatal("an empty handle reached the Provider")
		}
	}
}

// TestResolveProviderSessionHandleReportsUnsupportedWhenNotAdvertised proves a
// Provider that does not advertise resolve is never asked to mint a key, so the
// Endpoint can report the capability as absent instead of a fault.
func TestResolveProviderSessionHandleReportsUnsupportedWhenNotAdvertised(t *testing.T) {
	provider := newFakeProvider(t)
	binding := mustAdapter(t, provider)
	_, err := binding.ResolveProviderSessionHandle(context.Background(), "session-abc")
	if !errors.Is(err, adapter.ErrUnsupported) {
		t.Fatalf("resolve error = %v, want ErrUnsupported", err)
	}
	for _, request := range provider.requests {
		if request.Function == providercli.FunctionResolve {
			t.Fatal("a Provider that does not advertise resolve was asked to mint a key")
		}
	}
}

// TestResolveProviderSessionHandleRejectsAMissingResolution proves a success
// response without a resolution is a fault, not an empty mapping.
func TestResolveProviderSessionHandleRejectsAMissingResolution(t *testing.T) {
	provider := resolveProvider(t, nil)
	binding := mustAdapter(t, provider)
	if _, err := binding.ResolveProviderSessionHandle(context.Background(), "session-abc"); err == nil {
		t.Fatal("a success response without a resolution was accepted")
	}
}

// TestResolveProviderSessionHandleRejectsAnUnknownResourceKind proves the
// adapter does not record a mapping outside the closed Cluster vocabulary.
func TestResolveProviderSessionHandleRejectsAnUnknownResourceKind(t *testing.T) {
	provider := resolveProvider(t, &providercli.ResolutionResult{ProviderResourceKey: "provider-minted-key", ResourceKind: "not_a_kind"})
	binding := mustAdapter(t, provider)
	if _, err := binding.ResolveProviderSessionHandle(context.Background(), "session-abc"); err == nil {
		t.Fatal("an unknown resource kind was recorded")
	}
}

// TestResolveProviderSessionHandleRejectsAnEmptyKey proves an empty key is a
// fault rather than a mapping that can never be looked up again.
func TestResolveProviderSessionHandleRejectsAnEmptyKey(t *testing.T) {
	provider := resolveProvider(t, &providercli.ResolutionResult{ProviderResourceKey: "", ResourceKind: protocol.ResourceSession})
	binding := mustAdapter(t, provider)
	if _, err := binding.ResolveProviderSessionHandle(context.Background(), "session-abc"); err == nil {
		t.Fatal("an empty provider resource key was recorded")
	}
}

// TestResolveProviderSessionHandleSurfacesProviderFailure proves a Provider
// error is reported instead of being turned into a mapping.
func TestResolveProviderSessionHandleSurfacesProviderFailure(t *testing.T) {
	provider := newFakeProvider(t)
	provider.invoke = func(request providercli.Request) (providercli.Response, error) {
		if request.Function == providercli.FunctionDescribe {
			return describeResponseWithFunctions(request, providercli.FunctionResolve), nil
		}
		failure := &providercli.ProviderError{Code: "invalid_request", Message: "handle rejected"}
		return providercli.Response{Version: request.Version, RequestID: request.RequestID, OK: false, Error: failure}, nil
	}
	binding := mustAdapter(t, provider)
	_, err := binding.ResolveProviderSessionHandle(context.Background(), "session-abc")
	if err == nil || !strings.Contains(err.Error(), "handle rejected") {
		t.Fatalf("resolve error = %v, want the provider message", err)
	}
}
