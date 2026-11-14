//go:build !unix

package commandexec

import "os/exec"

// configureProcessGroup is a no-op where process groups are unavailable.
func configureProcessGroup(*exec.Cmd) {}

// killProcessGroup terminates the exact direct child on this platform.
func killProcessGroup(command *exec.Cmd) error {
	if command == nil || command.Process == nil {
		return nil
	}
	return command.Process.Kill()
}
