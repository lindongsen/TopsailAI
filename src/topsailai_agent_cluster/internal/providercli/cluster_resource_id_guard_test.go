package providercli

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

// clusterResourceIDFixture is a value with the exact shape the Endpoint mints.
// It is built from the shared prefix and a fixed suffix rather than written as a
// literal, so a change to the prefix cannot leave this fixture testing a shape
// that no longer exists.
func clusterResourceIDFixture() string {
	return protocol.ClusterResourceIDPrefix + strings.Repeat("0123456789abcdef", 2)
}

// TestClusterResourceIDsAreRejectedAtEveryProviderKeySite fails when any place
// that accepts a provider-private key also accepts a Cluster resource ID.
//
// The contract states that Cluster resource IDs never cross into provider
// authority, and the Endpoint alone maps a provider key to a Cluster ID. A
// provider that accepted one would address a resource by an identity it cannot
// resolve, so the rejection has to happen at every entry point rather than at
// whichever one a caller happens to use.
func TestClusterResourceIDsAreRejectedAtEveryProviderKeySite(t *testing.T) {
	clusterID := clusterResourceIDFixture()
	if !protocol.IsClusterResourceID(clusterID) {
		t.Fatalf("the fixture %q does not have the Cluster resource ID shape, so this guard checked nothing", clusterID)
	}
	sites := []struct {
		name     string
		validate func() error
	}{
		{
			name: "request target",
			validate: func() error {
				return Target{ResourceKind: protocol.ResourceSession, ProviderResourceKey: clusterID}.validate(false)
			},
		},
		{
			name: "provider observation",
			validate: func() error {
				return ProviderObservation{
					ProviderResourceKey: clusterID,
					ResourceKind:        protocol.ResourceSession,
					State:               protocol.SessionStateRunning,
					ObservedAtMS:        1794470400000,
				}.validate()
			},
		},
		{
			name: "typed query provider key",
			validate: func() error {
				return validateTypedProviderKey(protocol.ResourceSession, protocol.ResourceSession, clusterID)
			},
		},
		{
			name: "model select payload",
			validate: func() error {
				return ModelSelectPayload{ProviderResourceKey: clusterID}.Validate()
			},
		},
		{
			// The batch read carries its members in the payload rather than in a
			// target, so it is a separate site: a guard that only covered targets
			// left this one accepting a Cluster identity while the single-session
			// read refused it.
			name: "metrics batch payload member",
			validate: func() error {
				payload, err := json.Marshal(SessionMetricsBatchPayload{ProviderSessionIDs: []string{clusterID}})
				if err != nil {
					return err
				}
				_, err = DecodeQueryPayload(NamedContract{Name: QuerySessionMetricsBatch, Version: "v1"}, nil, payload)
				return err
			},
		},
	}
	if len(sites) == 0 {
		t.Fatal("no provider key site was enumerated, so this guard checked nothing")
	}
	for _, site := range sites {
		err := site.validate()
		if err == nil {
			t.Errorf("%s accepts the Cluster resource ID %q, so a Cluster identity can cross into provider authority", site.name, clusterID)
			continue
		}
		if !strings.Contains(err.Error(), "Cluster resource ID") {
			t.Errorf("%s rejects the Cluster resource ID for an unrelated reason (%v), so the rejection is not the one this row requires", site.name, err)
		}
	}
}

// TestProviderPrivateKeysAreStillAccepted fails when the Cluster ID rejection is
// so broad that it also refuses a legitimate provider key. A guard that rejects
// everything would pass the test above while breaking every real provider.
func TestProviderPrivateKeysAreStillAccepted(t *testing.T) {
	keys := []string{
		"session:stable",
		"provider-private-key",
		"res_short",
		"res_0123456789abcdef0123456789abcde",
		"res_0123456789ABCDEF0123456789abcdef",
		"res_0123456789abcdef0123456789abcdef0",
		"RES_0123456789abcdef0123456789abcdef",
	}
	if len(keys) == 0 {
		t.Fatal("no provider key was enumerated, so this guard checked nothing")
	}
	for _, key := range keys {
		if protocol.IsClusterResourceID(key) {
			t.Errorf("%q is treated as a Cluster resource ID, so a legitimate provider key would be refused", key)
		}
		if err := validateProviderResourceKey("provider_resource_key", key, true); err != nil {
			t.Errorf("validateProviderResourceKey rejects the legitimate provider key %q: %v", key, err)
		}
	}
}

// TestClusterResourceIDShapeMatchesTheMintingSide fails when the Endpoint mints
// IDs with a spelling the rejection no longer recognises. The prefix lives in one
// constant precisely so the two sides cannot drift, and this test proves the
// minting side actually uses it instead of repeating the literal.
func TestClusterResourceIDShapeMatchesTheMintingSide(t *testing.T) {
	root := filepath.Join(schemaDirectory(t), "..", "..", "..")
	source, err := os.ReadFile(filepath.Join(root, "internal", "storage", "endpoint", "mapping.go"))
	if err != nil {
		t.Fatalf("read the minting source: %v", err)
	}
	text := string(source)
	if !strings.Contains(text, "protocol.ClusterResourceIDPrefix") {
		t.Errorf("internal/storage/endpoint/mapping.go does not build the ID from protocol.ClusterResourceIDPrefix, so the minting side and the rejection can drift apart")
	}
	if strings.Contains(text, `"res_"`) {
		t.Errorf("internal/storage/endpoint/mapping.go still spells the prefix as a literal, so a change to the constant would leave the minting side behind")
	}
}

// TestContractStillForbidsClusterIDsInProviderAuthority fails when the document
// that states the prohibition stops stating it. The code rejects the value, and
// the contract is what tells a provider author why.
func TestContractStillForbidsClusterIDsInProviderAuthority(t *testing.T) {
	root := filepath.Join(schemaDirectory(t), "..", "..", "..")
	source, err := os.ReadFile(filepath.Join(root, "docs", "agent-cluster-protocol.md"))
	if err != nil {
		t.Fatalf("read the protocol document: %v", err)
	}
	text := string(source)
	if !strings.Contains(text, "Cluster resource IDs never cross into provider authority") {
		t.Errorf("docs/agent-cluster-protocol.md no longer states that Cluster resource IDs never cross into provider authority, so the rejection has no documented reason")
	}
}
