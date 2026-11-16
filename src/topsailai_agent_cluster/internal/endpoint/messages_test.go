package endpoint

import (
	"context"
	"errors"
	"fmt"
	"testing"

	"topsailai_agent_cluster/internal/adapter"
	"topsailai_agent_cluster/internal/protocol"
)

// messagesAdapter supplies read-only provider conversation evidence for executor
// routing.
type messagesAdapter struct {
	timeoutAdapter
	fail bool
}

// Messages returns one recorded message, or a provider failure when fail is set.
func (a messagesAdapter) Messages(context.Context, protocol.MessagesQuery) (protocol.MessagesResult, error) {
	if a.fail {
		return protocol.MessagesResult{}, errors.New("provider unavailable")
	}
	return protocol.MessagesResult{Messages: []protocol.Message{{Role: "user", Content: "hello"}}}, nil
}

// messagesBusyAdapter reproduces a capacity refusal: the adapter never reached the
// provider because another invocation of the same Adapter instance held the slot.
type messagesBusyAdapter struct{ timeoutAdapter }

// Messages reports a capacity refusal instead of provider evidence.
func (a messagesBusyAdapter) Messages(context.Context, protocol.MessagesQuery) (protocol.MessagesResult, error) {
	return protocol.MessagesResult{}, fmt.Errorf("%w: discovery", adapter.ErrBusy)
}

// TestExecutorMessagesRouting validates live handler selection and provider failure.
func TestExecutorMessagesRouting(t *testing.T) {
	for _, fail := range []bool{false, true} {
		registry := adapter.NewRegistry()
		registry.RegisterType("test", func(context.Context, adapter.Config) (adapter.Adapter, error) {
			return messagesAdapter{fail: fail}, nil
		})
		registry.Configure(context.Background(), adapter.Config{AdapterID: "a1", ProviderType: "test"})
		e := &Executor{registry: registry}
		result, err := e.Messages(context.Background(), protocol.MessagesQuery{})
		if (err != nil) != fail {
			t.Fatalf("%#v %v", result, err)
		}
		if fail {
			if result.ErrorCode != protocol.MessagesProviderError {
				t.Fatalf("failure code %q", result.ErrorCode)
			}
			continue
		}
		if len(result.Messages) != 1 || result.Messages[0].Content != "hello" {
			t.Fatalf("%#v", result)
		}
	}
}

// TestExecutorMessagesBusyIsNotProviderFailure proves a capacity refusal is not
// reported as a provider failure. The provider was never invoked, so the operator
// must be told to retry rather than to investigate a provider that never ran.
func TestExecutorMessagesBusyIsNotProviderFailure(t *testing.T) {
	registry := adapter.NewRegistry()
	registry.RegisterType("test", func(context.Context, adapter.Config) (adapter.Adapter, error) {
		return messagesBusyAdapter{}, nil
	})
	registry.Configure(context.Background(), adapter.Config{AdapterID: "a1", ProviderType: "test"})
	e := &Executor{registry: registry}
	result, err := e.Messages(context.Background(), protocol.MessagesQuery{})
	if !errors.Is(err, adapter.ErrBusy) {
		t.Fatalf("err=%v", err)
	}
	if result.ErrorCode != protocol.AdapterBusy {
		t.Fatalf("busy code %q want %q", result.ErrorCode, protocol.AdapterBusy)
	}
	if result.ErrorCode == protocol.MessagesProviderError {
		t.Fatal("capacity refusal was reported as a provider failure")
	}
}

// TestExecutorMessagesUnsupported verifies an adapter without the optional
// interface reports the capability as absent instead of an empty success.
func TestExecutorMessagesUnsupported(t *testing.T) {
	registry := adapter.NewRegistry()
	registry.RegisterType("test", func(context.Context, adapter.Config) (adapter.Adapter, error) { return timeoutAdapter{}, nil })
	registry.Configure(context.Background(), adapter.Config{AdapterID: "a1", ProviderType: "test"})
	e := &Executor{registry: registry}
	result, err := e.Messages(context.Background(), protocol.MessagesQuery{})
	if !errors.Is(err, adapter.ErrUnsupported) || result.ErrorCode != protocol.MessagesUnsupported {
		t.Fatalf("%#v %v", result, err)
	}
	if result.Messages != nil {
		t.Fatal("unsupported capability returned messages")
	}
}
