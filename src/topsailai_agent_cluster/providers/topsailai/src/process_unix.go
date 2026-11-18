//go:build unix

package main

import (
	"errors"
	"os/exec"
	"syscall"
)

// configureProcessGroup isolates one business CLI invocation and its helpers.
func configureProcessGroup(command *exec.Cmd) {
	command.SysProcAttr = &syscall.SysProcAttr{Setpgid: true}
}

// killProcessGroup terminates only the process group owned by this invocation.
func killProcessGroup(command *exec.Cmd) error {
	if command == nil || command.Process == nil {
		return nil
	}
	if err := syscall.Kill(-command.Process.Pid, syscall.SIGKILL); err != nil && !errors.Is(err, syscall.ESRCH) {
		return command.Process.Kill()
	}
	return nil
}
