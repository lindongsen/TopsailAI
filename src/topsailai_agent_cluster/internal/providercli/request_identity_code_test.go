package providercli

import (
	"errors"
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

// clusterResourceIDForCode is a value with the exact shape the Endpoint mints.
// It is built from the shared prefix rather than written as a literal, so a change
// to the prefix cannot leave this fixture testing a shape that no longer exists.
func clusterResourceIDForCode() string {
	return protocol.ClusterResourceIDPrefix + strings.Repeat("0123456789abcdef", 2)
}

// TestRejectedProviderKeyCarriesTheCallerErrorCode proves the rejection reports a
// caller-error code rather than only a message.
//
// The code is what lets the Endpoint and the Server classify the failure. Without
// it the rejection is indistinguishable from a provider fault once it leaves this
// package, and the operator is sent to investigate a provider that was never
// invoked.
func TestRejectedProviderKeyCarriesTheCallerErrorCode(t *testing.T) {
	clusterID := clusterResourceIDForCode()
	if !protocol.IsClusterResourceID(clusterID) {
		t.Fatalf("the fixture %q does not have the Cluster resource ID shape, so this guard checked nothing", clusterID)
	}
	err := validateProviderResourceKey("provider_resource_key", clusterID, true)
	if err == nil {
		t.Fatal("a Cluster resource ID was accepted where a provider-private key belongs")
	}
	var coded interface{ ErrorCode() string }
	if !errors.As(err, &coded) {
		t.Fatalf("the rejection carries no error code, so no caller can classify it: %v", err)
	}
	if got := coded.ErrorCode(); got != protocol.InvalidTarget {
		t.Fatalf("rejection code=%q want=%q", got, protocol.InvalidTarget)
	}
}

// TestRejectedProviderKeyKeepsItsMessage proves the classification did not cost the
// diagnostic text.
//
// The message names the offending value, which is the only part of the failure that
// tells the operator what to change. A code without the message would be a caller
// error the caller cannot act on.
func TestRejectedProviderKeyKeepsItsMessage(t *testing.T) {
	clusterID := clusterResourceIDForCode()
	err := validateProviderResourceKey("provider_resource_key", clusterID, true)
	if err == nil {
		t.Fatal("a Cluster resource ID was accepted where a provider-private key belongs")
	}
	message := err.Error()
	if !strings.Contains(message, "provider_resource_key") {
		t.Fatalf("message=%q does not name the rejected field", message)
	}
	if !strings.Contains(message, clusterID) {
		t.Fatalf("message=%q does not name the rejected value", message)
	}
	if !strings.Contains(message, "provider-private key") {
		t.Fatalf("message=%q does not say which identity is required", message)
	}
}

// TestLegitimateProviderKeyCarriesNoCode proves the classification is not applied
// to a value that is already correct.
//
// A guard that rejected every key would pass the two tests above while making the
// surface unusable, so the accepting path needs its own assertion.
func TestLegitimateProviderKeyCarriesNoCode(t *testing.T) {
	for _, key := range []string{"session:stable", "wa-5421006dfe45", "sad-abc123"} {
		if err := validateProviderResourceKey("provider_resource_key", key, true); err != nil {
			t.Fatalf("the legitimate provider key %q was rejected: %v", key, err)
		}
	}
}
