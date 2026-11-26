//go:build linux

package genericcli

import (
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"syscall"
	"time"
)

// configureProcessGroup gives one Provider CLI invocation its own session.
// Descendants may create separate process groups for their own cleanup without
// escaping the invocation ownership boundary.
func configureProcessGroup(command *exec.Cmd) {
	command.SysProcAttr = &syscall.SysProcAttr{Setsid: true}
}

// killProcessGroup terminates every process group in the invocation session.
func killProcessGroup(command *exec.Cmd) error {
	if command == nil || command.Process == nil {
		return nil
	}
	groups, err := invocationProcessGroups(command.Process.Pid)
	if err != nil {
		return killDirectProcessGroup(command)
	}
	var failures []error
	for _, group := range groups {
		if signalErr := syscall.Kill(-group, syscall.SIGKILL); signalErr != nil && !errors.Is(signalErr, syscall.ESRCH) {
			failures = append(failures, fmt.Errorf("kill provider process group %d: %w", group, signalErr))
		}
	}
	if len(groups) == 0 {
		if signalErr := killDirectProcessGroup(command); signalErr != nil {
			failures = append(failures, signalErr)
		}
	}
	return errors.Join(failures...)
}

func killDirectProcessGroup(command *exec.Cmd) error {
	if err := syscall.Kill(-command.Process.Pid, syscall.SIGKILL); err != nil && !errors.Is(err, syscall.ESRCH) {
		if processErr := command.Process.Kill(); processErr != nil && !errors.Is(processErr, os.ErrProcessDone) {
			return errors.Join(err, processErr)
		}
	}
	return nil
}

func processGroupAlive(command *exec.Cmd) bool {
	if command == nil || command.Process == nil {
		return false
	}
	groups, err := invocationProcessGroups(command.Process.Pid)
	return err == nil && len(groups) > 0
}

func waitForProcessGroupExit(command *exec.Cmd, timeout time.Duration) error {
	deadline := time.Now().Add(timeout)
	for processGroupAlive(command) {
		_ = killProcessGroup(command)
		if time.Now().After(deadline) {
			return fmt.Errorf("provider invocation session %d is still alive", command.Process.Pid)
		}
		time.Sleep(10 * time.Millisecond)
	}
	return nil
}

// invocationProcessGroups returns every process group still belonging to the
// session whose ID is the Provider process PID created by Setsid.
func invocationProcessGroups(sessionID int) ([]int, error) {
	entries, err := os.ReadDir("/proc")
	if err != nil {
		return nil, fmt.Errorf("read process table: %w", err)
	}
	groups := make(map[int]struct{})
	for _, entry := range entries {
		if !entry.IsDir() {
			continue
		}
		if _, parseErr := strconv.Atoi(entry.Name()); parseErr != nil {
			continue
		}
		group, session, statErr := processGroupAndSession(filepath.Join("/proc", entry.Name(), "stat"))
		if statErr != nil || session != sessionID || group <= 0 {
			continue
		}
		groups[group] = struct{}{}
	}
	result := make([]int, 0, len(groups))
	for group := range groups {
		result = append(result, group)
	}
	return result, nil
}

func processGroupAndSession(path string) (int, int, error) {
	document, err := os.ReadFile(path)
	if err != nil {
		return 0, 0, err
	}
	closing := strings.LastIndexByte(string(document), ')')
	if closing < 0 || closing+2 >= len(document) {
		return 0, 0, errors.New("invalid process stat")
	}
	fields := strings.Fields(string(document[closing+2:]))
	if len(fields) < 4 {
		return 0, 0, errors.New("incomplete process stat")
	}
	group, err := strconv.Atoi(fields[2])
	if err != nil {
		return 0, 0, err
	}
	session, err := strconv.Atoi(fields[3])
	if err != nil {
		return 0, 0, err
	}
	return group, session, nil
}
