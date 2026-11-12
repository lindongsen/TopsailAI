//go:build unix

package providerconformance

import (
	"errors"
	"fmt"
	"os/exec"
	"syscall"
	"time"
)

// configureProcessGroup isolates one invocation and all helpers in an owned process group.
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

// processGroupAlive reports whether any process remains in the invocation group.
func processGroupAlive(command *exec.Cmd) bool {
	if command == nil || command.Process == nil {
		return false
	}
	err := syscall.Kill(-command.Process.Pid, 0)
	return err == nil || errors.Is(err, syscall.EPERM)
}

// waitForProcessGroupExit waits until exact invocation cleanup becomes observable.
func waitForProcessGroupExit(command *exec.Cmd, timeout time.Duration) error {
	deadline := time.Now().Add(timeout)
	for processGroupAlive(command) {
		if time.Now().After(deadline) {
			return fmt.Errorf("process group %d is still alive", command.Process.Pid)
		}
		time.Sleep(10 * time.Millisecond)
	}
	return nil
}

// processAlive reports whether one test-observed process still exists.
func processAlive(pid int) bool {
	err := syscall.Kill(pid, 0)
	return err == nil || errors.Is(err, syscall.EPERM)
}
