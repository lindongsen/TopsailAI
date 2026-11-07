//go:build unix

package topsailai

import (
	"os/exec"
	"syscall"
)

// configureProcessGroup puts the child in its own process group so that a
// timeout terminates the whole tree it spawned. Killing only the direct child
// would leave grandchildren running after the Endpoint reported the command
// finished.
func configureProcessGroup(cmd *exec.Cmd) {
	if cmd.SysProcAttr == nil {
		cmd.SysProcAttr = &syscall.SysProcAttr{}
	}
	cmd.SysProcAttr.Setpgid = true
}

// killProcessGroup terminates the child's whole process group.
func killProcessGroup(cmd *exec.Cmd) error {
	if cmd.Process == nil {
		return nil
	}
	// The negative PID addresses the group created by Setpgid. Fall back to the
	// single process when the group is already gone, so cancellation still
	// reports a definite outcome instead of a spurious error.
	if err := syscall.Kill(-cmd.Process.Pid, syscall.SIGKILL); err != nil {
		return cmd.Process.Kill()
	}
	return nil
}
