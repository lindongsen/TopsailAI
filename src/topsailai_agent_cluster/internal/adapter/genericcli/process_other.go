//go:build !unix

package genericcli

import (
	"os/exec"
	"time"
)

// configureProcessGroup is a no-op where process groups are unavailable.
func configureProcessGroup(*exec.Cmd) {}

// killProcessGroup terminates the exact direct child on this platform.
func killProcessGroup(command *exec.Cmd) error {
	if command == nil || command.Process == nil {
		return nil
	}
	return command.Process.Kill()
}

func processGroupAlive(*exec.Cmd) bool { return false }

func waitForProcessGroupExit(*exec.Cmd, time.Duration) error { return nil }
