//go:build !unix

package tui

import "os/exec"

// configureTriggerProcessGroup is a no-op where process groups are unavailable.
// The script is still bounded by its context and killed directly, so a timeout
// remains definite even though a grandchild cannot be addressed as a group.
func configureTriggerProcessGroup(cmd *exec.Cmd) {}

// killTriggerProcessGroup terminates the script process directly.
func killTriggerProcessGroup(cmd *exec.Cmd) error {
	if cmd.Process == nil {
		return nil
	}
	return cmd.Process.Kill()
}
