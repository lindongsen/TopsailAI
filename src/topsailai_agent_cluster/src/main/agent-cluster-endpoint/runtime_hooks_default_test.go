//go:build !testhooks

package main

import (
	"testing"
	"time"
)

func TestCollectionDelayEnvironmentPrefersEndpointName(t *testing.T) {
	t.Setenv("AGENT_CLUSTER_ENDPOINT_COLLECTION_DELAY_MS", "250")
	t.Setenv("AGENT_CLUSTER_COLLECTION_DELAY_MS", "500")
	if got := newRuntimeHooks(nil, "").CollectionDelay; got != 250*time.Millisecond {
		t.Fatalf("collection delay = %s", got)
	}
}

func TestCollectionDelayEnvironmentUsesDeprecatedFallback(t *testing.T) {
	t.Setenv("AGENT_CLUSTER_COLLECTION_DELAY_MS", "500")
	if got := newRuntimeHooks(nil, "").CollectionDelay; got != 500*time.Millisecond {
		t.Fatalf("collection delay = %s", got)
	}
}

func TestCollectionDelayEnvironmentRejectsInvalidOwnedValue(t *testing.T) {
	t.Setenv("AGENT_CLUSTER_ENDPOINT_COLLECTION_DELAY_MS", "invalid")
	t.Setenv("AGENT_CLUSTER_COLLECTION_DELAY_MS", "250")
	if got := newRuntimeHooks(nil, "").CollectionDelay; got != 5*time.Second {
		t.Fatalf("collection delay = %s", got)
	}
}
