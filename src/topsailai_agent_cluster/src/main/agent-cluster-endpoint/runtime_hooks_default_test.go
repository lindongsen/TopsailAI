//go:build !testhooks

package main

import (
	"testing"
	"time"
)

func TestCollectionDelayEnvironmentUsesEndpointName(t *testing.T) {
	t.Setenv("AGENT_CLUSTER_ENDPOINT_COLLECTION_DELAY_MS", "250")
	if got := newRuntimeHooks(nil, "").CollectionDelay; got != 250*time.Millisecond {
		t.Fatalf("collection delay = %s", got)
	}
}

// TestCollectionDelayEnvironmentIgnoresDeprecatedName pins the removal of the
// compatibility fallback. A deprecated name must not configure the delay, so an
// operator who still exports one gets the default instead of a silently
// different collection cadence.
func TestCollectionDelayEnvironmentIgnoresDeprecatedName(t *testing.T) {
	t.Setenv("AGENT_CLUSTER_COLLECTION_DELAY_MS", "500")
	if got := newRuntimeHooks(nil, "").CollectionDelay; got != 5*time.Second {
		t.Fatalf("collection delay = %s, want the 5s default", got)
	}
}

func TestCollectionDelayEnvironmentRejectsInvalidOwnedValue(t *testing.T) {
	t.Setenv("AGENT_CLUSTER_ENDPOINT_COLLECTION_DELAY_MS", "invalid")
	if got := newRuntimeHooks(nil, "").CollectionDelay; got != 5*time.Second {
		t.Fatalf("collection delay = %s", got)
	}
}
