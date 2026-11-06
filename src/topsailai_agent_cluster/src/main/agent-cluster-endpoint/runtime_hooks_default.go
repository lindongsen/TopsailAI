//go:build !testhooks

package main

import (
	"log/slog"
	"os"
	"strconv"
	"time"
)

type runtimeHooks struct {
	BeforeInvocation func()
	CollectionDelay  time.Duration
	ReceiptDelay     time.Duration
}

func newRuntimeHooks(logger *slog.Logger, _ string) runtimeHooks {
	return runtimeHooks{CollectionDelay: collectionDelayEnv(logger, "AGENT_CLUSTER_COLLECTION_DELAY_MS", 5*time.Second)}
}

// collectionDelayEnv reads the post-collection delay from the process boundary.
// A non-positive or unparsable value falls back to the default so a typo cannot
// turn the Endpoint into a busy collection loop.
func collectionDelayEnv(logger *slog.Logger, name string, fallback time.Duration) time.Duration {
	value := os.Getenv(name)
	if value == "" {
		return fallback
	}
	parsed, err := strconv.ParseInt(value, 10, 64)
	if err != nil || parsed <= 0 {
		if logger != nil {
			logger.Warn("invalid collection delay", "name", name, "value", value, "error", err)
		}
		return fallback
	}
	return time.Duration(parsed) * time.Millisecond
}

func (runtimeHooks) announceHold(string) error                 { return nil }
func (runtimeHooks) waitForRelease(*slog.Logger, string) error { return nil }
func (runtimeHooks) waitForHold(*slog.Logger, string) error    { return nil }
