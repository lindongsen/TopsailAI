package tui

import (
	"context"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

// versionStubAPI advertises a descriptor whose capabilities carry explicit
// versions, so the intent version can be proven to follow the advertisement.
type versionStubAPI struct {
	interactiveStub
	descriptor protocol.CapabilityDescriptor
}

func (s *versionStubAPI) GetCapabilities(context.Context, string) (protocol.CapabilityDescriptor, error) {
	return s.descriptor, nil
}

// TestCapabilityVersionFollowsAdvertisement proves the intent carries the
// advertised version rather than a hardcoded default. The Endpoint matches a
// capability on both name and version, so a hardcoded "v1" would make an
// advertised operation such as command.exec (version "1") unreachable.
func TestCapabilityVersionFollowsAdvertisement(t *testing.T) {
	descriptor := protocol.CapabilityDescriptor{
		Revision: "rev-1",
		Capabilities: []protocol.Capability{
			{Name: protocol.OperationCommandExec, Version: protocol.CommandExecPayloadVersion},
			{Name: protocol.OperationMessageSend, Version: "v1"},
		},
	}
	version, err := CapabilityVersion(descriptor, protocol.OperationCommandExec)
	if err != nil {
		t.Fatalf("CapabilityVersion returned error: %v", err)
	}
	if version != protocol.CommandExecPayloadVersion {
		t.Fatalf("version = %q, want %q", version, protocol.CommandExecPayloadVersion)
	}
	if version == "v1" {
		t.Fatalf("version must not be the hardcoded default for command.exec")
	}
}

// TestCapabilityVersionFallsBackWhenUnadvertisedVersion proves an Endpoint that
// advertises no version keeps the historical default. An empty version could
// never be admitted, because an immutable intent requires a non-empty operation
// version, so the fallback preserves the previous behaviour.
func TestCapabilityVersionFallsBackWhenUnadvertisedVersion(t *testing.T) {
	descriptor := protocol.CapabilityDescriptor{
		Revision:     "rev-1",
		Capabilities: []protocol.Capability{{Name: protocol.OperationMessageSend}},
	}
	version, err := CapabilityVersion(descriptor, protocol.OperationMessageSend)
	if err != nil {
		t.Fatalf("CapabilityVersion returned error: %v", err)
	}
	if version != defaultOperationVersion {
		t.Fatalf("version = %q, want %q", version, defaultOperationVersion)
	}
}

// TestCapabilityVersionRejectsUnadvertisedOperation proves an operation the
// Endpoint does not advertise is refused before an intent is built.
func TestCapabilityVersionRejectsUnadvertisedOperation(t *testing.T) {
	descriptor := protocol.CapabilityDescriptor{
		Revision:     "rev-1",
		Capabilities: []protocol.Capability{{Name: protocol.OperationMessageSend, Version: "v1"}},
	}
	if _, err := CapabilityVersion(descriptor, protocol.OperationCommandExec); err == nil {
		t.Fatal("expected an error for an unadvertised operation")
	}
}

// TestPrepareActionUsesAdvertisedVersion proves the assembled intent carries the
// advertised version end to end, so an advertised command.exec intent is not
// rejected by the Endpoint as unsupported.
func TestPrepareActionUsesAdvertisedVersion(t *testing.T) {
	api := &versionStubAPI{descriptor: protocol.CapabilityDescriptor{
		Revision:     "rev-1",
		Capabilities: []protocol.Capability{{Name: protocol.OperationCommandExec, Version: protocol.CommandExecPayloadVersion}},
	}}
	runner := CommandRunner{API: api, NewID: func() string { return "cmd-1" }}
	intent, err := runner.PrepareAction(context.Background(), ActionRequest{
		Operation:          protocol.OperationCommandExec,
		EndpointID:         "endpoint-1",
		ResourceID:         "session-1",
		ProviderGeneration: "gen-1",
		Payload:            []byte(`{"argv":["echo","hello"]}`),
		Confirmed:          true,
		OperationLabel:     "exec",
	})
	if err != nil {
		t.Fatalf("PrepareAction returned error: %v", err)
	}
	if intent.OperationVersion != protocol.CommandExecPayloadVersion {
		t.Fatalf("OperationVersion = %q, want %q", intent.OperationVersion, protocol.CommandExecPayloadVersion)
	}
	if intent.CapabilityRevision != "rev-1" {
		t.Fatalf("CapabilityRevision = %q, want rev-1", intent.CapabilityRevision)
	}
	if intent.Target == nil || intent.Target.ResourceID != "session-1" || intent.Target.ProviderGeneration != "gen-1" {
		t.Fatalf("target = %+v, want session-1/gen-1", intent.Target)
	}
}
