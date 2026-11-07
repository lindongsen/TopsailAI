package adapter

import (
	"context"
	"errors"
	"os"
	"os/exec"
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

// TestBoundedProviderResponseKeepsSmallDocument proves a document within the
// bound is carried unchanged and is not labelled truncated.
func TestBoundedProviderResponseKeepsSmallDocument(t *testing.T) {
	document := `{"outcome":"accepted"}`
	got, truncated := BoundedProviderResponse(document)
	if got != document {
		t.Fatalf("document=%q want %q", got, document)
	}
	if truncated {
		t.Fatal("small document must not be labelled truncated")
	}
}

// TestBoundedProviderResponseTruncatesAtRuneBoundary proves an oversized
// document is bounded, labelled, and never split inside a multi-byte rune.
func TestBoundedProviderResponseTruncatesAtRuneBoundary(t *testing.T) {
	// A three-byte rune straddling the bound would leave invalid UTF-8 if the
	// document were cut at the byte limit.
	document := strings.Repeat("a", protocol.MaxProviderResponseBytes-1) + "世" + "tail"
	got, truncated := BoundedProviderResponse(document)
	if !truncated {
		t.Fatal("oversized document must be labelled truncated")
	}
	if len(got) > protocol.MaxProviderResponseBytes {
		t.Fatalf("bounded length=%d exceeds limit=%d", len(got), protocol.MaxProviderResponseBytes)
	}
	if strings.ContainsRune(got, '\uFFFD') {
		t.Fatal("truncation split a rune and produced invalid UTF-8")
	}
	if !strings.HasPrefix(got, "aaaa") {
		t.Fatalf("bounded document lost its prefix: %q", got[:8])
	}
}

// TestProviderFailureTextReadsExitErrorStderr proves the provider's own stderr
// is recovered through a wrapped exit error.
func TestProviderFailureTextReadsExitErrorStderr(t *testing.T) {
	exitErr := &exec.ExitError{Stderr: []byte("provider diagnostic")}
	wrapped := errors.Join(errors.New("execute adapter"), exitErr)
	if got := ProviderFailureText(wrapped); got != "provider diagnostic" {
		t.Fatalf("failure text=%q want %q", got, "provider diagnostic")
	}
}

// TestProviderFailureTextIgnoresNonExitError proves a failure without captured
// stderr yields no fabricated diagnostic.
func TestProviderFailureTextIgnoresNonExitError(t *testing.T) {
	if got := ProviderFailureText(errors.New("no exit error")); got != "" {
		t.Fatalf("failure text=%q want empty", got)
	}
}

// TestCommandAdapterExecuteCarriesProviderDocument proves the generic adapter
// honours the documented contract: the provider's own answer is carried in the
// receipt instead of being discarded after decoding.
func TestCommandAdapterExecuteCarriesProviderDocument(t *testing.T) {
	t.Setenv("AGENT_CLUSTER_COMMAND_HELPER", "1")
	a := commandAdapterForTest(t, commandMapper{mapping: ResourceMapping{AdapterID: "adapter-1", ProviderKey: "native-1", ResourceID: "res-1"}})
	result, err := a.Execute(context.Background(), ExecuteRequest{Intent: protocol.ImmutableIntent{CommandID: "cmd-1", Operation: "message.send", Target: &protocol.CommandTarget{ResourceID: "res-1", Generation: "gen-1"}, Payload: []byte(`{"text":"hello"}`)}})
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(result.Receipt.ProviderResponse, `"effect_certainty":"acknowledged"`) {
		t.Fatalf("receipt does not carry the provider document: %#v", result.Receipt)
	}
	if result.Receipt.ProviderResponseTruncated {
		t.Fatal("small provider document must not be labelled truncated")
	}
}

// TestCommandAdapterExecuteCarriesProviderDiagnostic proves a failed invocation
// still surfaces the provider's own stderr, which is the only evidence of why
// the call failed.
func TestCommandAdapterExecuteCarriesProviderDiagnostic(t *testing.T) {
	t.Setenv("AGENT_CLUSTER_COMMAND_HELPER", "1")
	t.Setenv("AGENT_CLUSTER_COMMAND_HELPER_OUTPUT", "execute-fail")
	a := commandAdapterForTest(t, commandMapper{mapping: ResourceMapping{AdapterID: "adapter-1", ProviderKey: "native-1", ResourceID: "res-1"}})
	result, err := a.Execute(context.Background(), ExecuteRequest{Intent: protocol.ImmutableIntent{CommandID: "cmd-1", Operation: "message.send", Target: &protocol.CommandTarget{ResourceID: "res-1", Generation: "gen-1"}, Payload: []byte(`{"text":"hello"}`)}})
	if err == nil {
		t.Fatal("expected the provider failure to be reported")
	}
	if result.Receipt.EffectCertainty != protocol.EffectUnknown {
		t.Fatalf("effect certainty=%q want unknown", result.Receipt.EffectCertainty)
	}
	if !strings.Contains(result.Receipt.ProviderResponse, "helper provider diagnostic") {
		t.Fatalf("receipt does not carry the provider diagnostic: %#v", result.Receipt)
	}
}

// TestCommandAdapterExecuteCarriesUndecodableDocument proves a provider answer
// that cannot be decoded is still preserved as evidence rather than dropped.
func TestCommandAdapterExecuteCarriesUndecodableDocument(t *testing.T) {
	t.Setenv("AGENT_CLUSTER_COMMAND_HELPER", "1")
	t.Setenv("AGENT_CLUSTER_COMMAND_HELPER_OUTPUT", "execute-garbage")
	a := commandAdapterForTest(t, commandMapper{mapping: ResourceMapping{AdapterID: "adapter-1", ProviderKey: "native-1", ResourceID: "res-1"}})
	result, err := a.Execute(context.Background(), ExecuteRequest{Intent: protocol.ImmutableIntent{CommandID: "cmd-1", Operation: "message.send", Target: &protocol.CommandTarget{ResourceID: "res-1", Generation: "gen-1"}, Payload: []byte(`{"text":"hello"}`)}})
	if err == nil {
		t.Fatal("expected the decode failure to be reported")
	}
	if result.Receipt.ProviderResponse != "not a json document" {
		t.Fatalf("receipt does not carry the undecodable document: %#v", result.Receipt)
	}
}

// TestCommandAdapterExecuteKeepsReceiptOnSuccess proves the added document does
// not disturb the normalized receipt fields.
func TestCommandAdapterExecuteKeepsReceiptOnSuccess(t *testing.T) {
	t.Setenv("AGENT_CLUSTER_COMMAND_HELPER", "1")
	a := commandAdapterForTest(t, commandMapper{mapping: ResourceMapping{AdapterID: "adapter-1", ProviderKey: "native-1", ResourceID: "res-1"}})
	result, err := a.Execute(context.Background(), ExecuteRequest{Intent: protocol.ImmutableIntent{CommandID: "cmd-1", Operation: "message.send", Target: &protocol.CommandTarget{ResourceID: "res-1", Generation: "gen-1"}, Payload: []byte(`{"text":"hello"}`)}})
	if err != nil {
		t.Fatal(err)
	}
	if result.Receipt.CommandID != "cmd-1" {
		t.Fatalf("command ID=%q want cmd-1", result.Receipt.CommandID)
	}
	if result.Receipt.DeliveryBoundary != protocol.DeliverySubmitted {
		t.Fatalf("delivery boundary=%q want submitted", result.Receipt.DeliveryBoundary)
	}
	if result.Receipt.EffectCertainty != protocol.EffectAcknowledged {
		t.Fatalf("effect certainty=%q want acknowledged", result.Receipt.EffectCertainty)
	}
}

// TestCommandAdapterExecuteHelperIsReachable guards the test helper wiring: a
// missing helper mode would silently fall through to the success document and
// make the failure assertions meaningless.
func TestCommandAdapterExecuteHelperIsReachable(t *testing.T) {
	if os.Getenv("AGENT_CLUSTER_COMMAND_HELPER") != "" {
		t.Skip("helper process")
	}
	t.Setenv("AGENT_CLUSTER_COMMAND_HELPER", "1")
	t.Setenv("AGENT_CLUSTER_COMMAND_HELPER_OUTPUT", "execute-fail")
	a := commandAdapterForTest(t, commandMapper{mapping: ResourceMapping{AdapterID: "adapter-1", ProviderKey: "native-1", ResourceID: "res-1"}})
	result, err := a.Execute(context.Background(), ExecuteRequest{Intent: protocol.ImmutableIntent{CommandID: "cmd-1", Operation: "message.send", Target: &protocol.CommandTarget{ResourceID: "res-1", Generation: "gen-1"}, Payload: []byte(`{"text":"hello"}`)}})
	if err == nil {
		t.Fatal("helper failure mode was not reached")
	}
	if result.Receipt.ProviderResponse == "" {
		t.Fatal("helper failure mode produced no provider document")
	}
}
