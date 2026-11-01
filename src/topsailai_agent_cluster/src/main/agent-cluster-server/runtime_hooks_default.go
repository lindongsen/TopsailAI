//go:build !testhooks

package main

import (
	"log/slog"
	"time"
)

type runtimeHooks struct {
	DropAck       bool
	DispatchDelay time.Duration
	HoldPhase     string
	HoldDir       string
}

func newRuntimeHooks(_ *slog.Logger) runtimeHooks { return runtimeHooks{} }

func (runtimeHooks) waitForHold(*slog.Logger, string) error { return nil }
