//go:build !unix

package providerconformance

import (
	"os/exec"
	"time"
)

// configureProcessGroup has no portable process-group implementation on this platform.
func configureProcessGroup(_ *exec.Cmd) {}

// killProcessGroup terminates the directly owned process on this platform.
func killProcessGroup(command *exec.Cmd) error {
	if command == nil || command.Process == nil {
		return nil
	}
	return command.Process.Kill()
}

// processGroupAlive cannot inspect descendants portably on this platform.
func processGroupAlive(_ *exec.Cmd) bool {
	return false
}

// waitForProcessGroupExit has no portable descendant probe on this platform.
func waitForProcessGroupExit(_ *exec.Cmd, _ time.Duration) error {
	return nil
}

// processAlive has no portable process probe on this platform.
func processAlive(_ int) bool {
	return false
}
