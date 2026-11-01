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
	DropAck       bool
	DispatchDelay time.Duration
	HoldPhase     string
	HoldDir       string
}

func newRuntimeHooks(logger *slog.Logger) runtimeHooks {
	value := os.Getenv("AGENT_CLUSTER_TEST_DISPATCH_DELAY_MS")
	var delay time.Duration
	if value != "" {
		parsed, err := strconv.ParseInt(value, 10, 64)
		if err != nil || parsed < 0 {
			if logger != nil {
				logger.Warn("invalid test dispatch delay", "value", value, "error", err)
			}
		} else {
			delay = time.Duration(parsed) * time.Millisecond
		}
	}
	return runtimeHooks{DropAck: os.Getenv("AGENT_CLUSTER_TEST_DROP_ACK") == "1", DispatchDelay: delay, HoldPhase: os.Getenv("AGENT_CLUSTER_TEST_HOLD_PHASE"), HoldDir: os.Getenv("AGENT_CLUSTER_TEST_HOLD_DIR")}
}

// waitForHold pauses a testhook-only lifecycle phase until the scenario releases it.
func (h runtimeHooks) waitForHold(logger *slog.Logger, phase string) error {
	if h.HoldPhase != phase || h.HoldDir == "" {
		return nil
	}
	if err := os.MkdirAll(h.HoldDir, 0o700); err != nil {
		return err
	}
	if err := os.WriteFile(filepath.Join(h.HoldDir, "reached-server-"+phase), []byte("reached\n"), 0o600); err != nil {
		return err
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
