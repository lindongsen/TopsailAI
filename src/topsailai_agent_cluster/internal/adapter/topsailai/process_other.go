//go:build !unix

package topsailai

import "os/exec"

// configureProcessGroup is a no-op where process groups are unavailable.
func configureProcessGroup(*exec.Cmd) {}

// killProcessGroup terminates the direct child where process groups are unavailable.
func killProcessGroup(cmd *exec.Cmd) error {
	if cmd.Process == nil {
		return nil
	}
	return cmd.Process.Kill()
}
