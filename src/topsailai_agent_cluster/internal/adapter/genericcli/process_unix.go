//go:build unix

package genericcli

import (
	"errors"
	"fmt"
	"os/exec"
	"syscall"
	"time"
)

// configureProcessGroup isolates one Provider CLI invocation and its helpers.
func configureProcessGroup(command *exec.Cmd) {
	command.SysProcAttr = &syscall.SysProcAttr{Setpgid: true}
}

// killProcessGroup terminates only the group owned by this invocation.
func killProcessGroup(command *exec.Cmd) error {
	if command == nil || command.Process == nil {
		return nil
	}
	if err := syscall.Kill(-command.Process.Pid, syscall.SIGKILL); err != nil && !errors.Is(err, syscall.ESRCH) {
		return command.Process.Kill()
	}
	return nil
}

func processGroupAlive(command *exec.Cmd) bool {
	if command == nil || command.Process == nil {
		return false
	}
	err := syscall.Kill(-command.Process.Pid, 0)
	return err == nil || errors.Is(err, syscall.EPERM)
}

func waitForProcessGroupExit(command *exec.Cmd, timeout time.Duration) error {
	deadline := time.Now().Add(timeout)
	for processGroupAlive(command) {
		if time.Now().After(deadline) {
			return fmt.Errorf("provider process group %d is still alive", command.Process.Pid)
		}
		time.Sleep(10 * time.Millisecond)
	}
	return nil
}
