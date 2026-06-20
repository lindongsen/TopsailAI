// sleepy is a test helper binary that simulates a long-running daemon process.
// It is used by the daemon package unit tests to exercise Start/Stop/Restart
// without starting the real ACS server.
package main

import (
	"os"
	"os/signal"
	"syscall"

	"github.com/topsailai/agent-community/internal/daemon"
)

func main() {
	// Prepare daemon environment: redirect logs and write PID file.
	if err := daemon.SetupDaemon(); err != nil {
		os.Exit(1)
	}

	// Wait until SIGTERM/SIGINT, then clean up and exit.
	sigCh := make(chan os.Signal, 1)
	signal.Notify(sigCh, syscall.SIGTERM, syscall.SIGINT)
	<-sigCh

	_ = daemon.CleanupDaemon()
	os.Exit(0)
}
