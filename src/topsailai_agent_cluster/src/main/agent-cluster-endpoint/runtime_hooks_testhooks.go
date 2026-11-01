//go:build testhooks

package main

import (
	"fmt"
	"log/slog"
	"os"
	"path/filepath"
	"strconv"
	"time"
)

type runtimeHooks struct {
	BeforeInvocation   func()
	CollectionInterval time.Duration
	ReceiptDelay       time.Duration
	HoldPhase          string
	HoldDir            string
}

func newRuntimeHooks(logger *slog.Logger, databasePath string) runtimeHooks {
	return runtimeHooks{BeforeInvocation: crashBeforeInvocation(logger, databasePath), HoldPhase: os.Getenv("AGENT_CLUSTER_TEST_HOLD_PHASE"), HoldDir: os.Getenv("AGENT_CLUSTER_TEST_HOLD_DIR"), CollectionInterval: durationEnv(logger, "AGENT_CLUSTER_TEST_COLLECTION_INTERVAL_MS", 10*time.Second, false), ReceiptDelay: durationEnv(logger, "AGENT_CLUSTER_TEST_DELAY_RECEIPT_MS", 0, true)}
}

func durationEnv(logger *slog.Logger, name string, fallback time.Duration, allowZero bool) time.Duration {
	value := os.Getenv(name)
	if value == "" {
		return fallback
	}
	parsed, err := strconv.ParseInt(value, 10, 64)
	if err != nil || parsed < 0 || (!allowZero && parsed == 0) {
		if logger != nil {
			logger.Warn("invalid test duration", "name", name, "value", value, "error", err)
		}
		return fallback
	}
	return time.Duration(parsed) * time.Millisecond
}

func crashBeforeInvocation(logger *slog.Logger, databasePath string) func() {
	if os.Getenv("AGENT_CLUSTER_TEST_CRASH_BEFORE_INVOCATION") != "1" {
		return nil
	}
	marker := databasePath + ".crash-before-invocation"
	return func() {
		file, err := os.OpenFile(marker, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0o600)
		if err != nil {
			return
		}
		_ = file.Close()
		if logger != nil {
			logger.Warn("test crash after accepted journal phase", "phase", "accepted")
		}
		os.Exit(98)
	}
}

// announceHold records that the Endpoint reached a durable test phase.
func (h runtimeHooks) announceHold(phase string) error {
	if h.HoldPhase != phase || h.HoldDir == "" {
		return nil
	}
	if err := os.MkdirAll(h.HoldDir, 0o700); err != nil {
		return err
	}
	return os.WriteFile(filepath.Join(h.HoldDir, "reached-endpoint-"+phase), []byte("reached\n"), 0o600)
}

// waitForRelease waits for a bounded test phase release signal.
func (h runtimeHooks) waitForRelease(logger *slog.Logger, phase string) error {
	if h.HoldPhase != phase || h.HoldDir == "" {
		return nil
	}
	deadline := time.Now().Add(30 * time.Second)
	for time.Now().Before(deadline) {
		if _, err := os.Stat(filepath.Join(h.HoldDir, "release-"+phase)); err == nil {
			return nil
		} else if !os.IsNotExist(err) {
			return err
		}
		time.Sleep(15 * time.Millisecond)
	}
	if logger != nil {
		logger.Error("test phase hold timed out", "phase", phase)
	}
	return fmt.Errorf("test phase hold timed out: %s", phase)
}

// waitForHold announces and waits for a testhook-only lifecycle phase.
func (h runtimeHooks) waitForHold(logger *slog.Logger, phase string) error {
	if err := h.announceHold(phase); err != nil {
		return err
	}
	return h.waitForRelease(logger, phase)
}
