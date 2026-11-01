//go:build !testhooks

package main

import (
	"log/slog"
	"time"
)

type runtimeHooks struct {
	BeforeInvocation   func()
	CollectionInterval time.Duration
	ReceiptDelay       time.Duration
}

func newRuntimeHooks(_ *slog.Logger, _ string) runtimeHooks {
	return runtimeHooks{CollectionInterval: 10 * time.Second}
}

func (runtimeHooks) announceHold(string) error                 { return nil }
func (runtimeHooks) waitForRelease(*slog.Logger, string) error { return nil }
func (runtimeHooks) waitForHold(*slog.Logger, string) error    { return nil }
