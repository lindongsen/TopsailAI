//go:build linux

package genericcli

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"syscall"
	"testing"
	"time"

	"topsailai_agent_cluster/internal/protocol"
	"topsailai_agent_cluster/internal/providercli"
)

const (
	custodyHelperMode = "AGENT_CLUSTER_CUSTODY_HELPER_MODE"
	custodyHeldFile   = "AGENT_CLUSTER_CUSTODY_HELD_FILE"
	custodyPIDFile    = "AGENT_CLUSTER_CUSTODY_PID_FILE"
	custodyReadyFile  = "AGENT_CLUSTER_CUSTODY_READY_FILE"
)

// TestProcessCustodyHelper provides a Provider process and a detached helper
// process for TestInvokeStreamTimeoutKillsSeparateDescendantProcessGroup.
func TestProcessCustodyHelper(t *testing.T) {
	switch os.Getenv(custodyHelperMode) {
	case "provider":
		runCustodyProviderHelper()
	case "holder":
		runCustodyFileHolder()
	default:
		t.Skip("custody helper process only")
	}
}

func runCustodyProviderHelper() {
	executable, err := os.Executable()
	if err != nil {
		os.Exit(2)
	}
	command := exec.Command(executable, "-test.run=^TestProcessCustodyHelper$", "-test.count=1")
	command.Env = replaceEnvironment(os.Environ(), custodyHelperMode, "holder")
	command.SysProcAttr = &syscall.SysProcAttr{Setpgid: true}
	if err := command.Start(); err != nil {
		os.Exit(3)
	}
	pidFile := os.Getenv(custodyPIDFile)
	if err := os.WriteFile(pidFile, []byte(strconv.Itoa(command.Process.Pid)), 0o600); err != nil {
		_ = command.Process.Kill()
		os.Exit(4)
	}
	if !waitForCustodyReady(os.Getenv(custodyReadyFile), time.Second) {
		_ = command.Process.Kill()
		os.Exit(5)
	}
	fmt.Printf(`{"protocol":%q,"major":%d,"minor":%d,"request_id":"custody-follow","type":%q,"sequence":1}`+"\n",
		providercli.ProtocolName, providercli.ProtocolMajor, providercli.ProtocolMinor, providercli.FrameStarted)
	time.Sleep(10 * time.Second)
	os.Exit(0)
}

func runCustodyFileHolder() {
	file, err := os.Open(os.Getenv(custodyHeldFile))
	if err != nil {
		os.Exit(6)
	}
	defer file.Close()
	if err := os.WriteFile(os.Getenv(custodyReadyFile), []byte("ready"), 0o600); err != nil {
		os.Exit(7)
	}
	time.Sleep(10 * time.Second)
	os.Exit(0)
}

func waitForCustodyReady(path string, timeout time.Duration) bool {
	deadline := time.Now().Add(timeout)
	for time.Now().Before(deadline) {
		if _, err := os.Stat(path); err == nil {
			return true
		}
		time.Sleep(10 * time.Millisecond)
	}
	return false
}

func replaceEnvironment(environment []string, name string, value string) []string {
	result := make([]string, 0, len(environment)+1)
	prefix := name + "="
	for _, setting := range environment {
		if !strings.HasPrefix(setting, prefix) {
			result = append(result, setting)
		}
	}
	return append(result, prefix+value)
}

// TestInvokeStreamTimeoutKillsSeparateDescendantProcessGroup proves the outer
// invocation owns a Provider helper even when that helper creates a new process
// group. The helper holds a file open so the assertion covers the user-visible
// failure where resume cleanup sees an obsolete stdout file as still in use.
func TestInvokeStreamTimeoutKillsSeparateDescendantProcessGroup(t *testing.T) {
	executable, err := os.Executable()
	if err != nil {
		t.Fatalf("resolve test executable: %v", err)
	}
	directory := t.TempDir()
	heldPath := filepath.Join(directory, "session.stdout")
	pidPath := filepath.Join(directory, "holder.pid")
	readyPath := filepath.Join(directory, "holder.ready")
	if err := os.WriteFile(heldPath, []byte("old output"), 0o600); err != nil {
		t.Fatalf("write held file: %v", err)
	}
	environment := replaceEnvironment(os.Environ(), custodyHelperMode, "provider")
	environment = replaceEnvironment(environment, custodyHeldFile, heldPath)
	environment = replaceEnvironment(environment, custodyPIDFile, pidPath)
	environment = replaceEnvironment(environment, custodyReadyFile, readyPath)
	runner, err := newProcessRunner(runnerConfig{
		executable:     executable,
		args:           []string{"-test.run=^TestProcessCustodyHelper$", "-test.count=1"},
		environment:    environment,
		timeout:        2 * time.Second,
		followTimeout:  300 * time.Millisecond,
		maxStdinBytes:  1 << 20,
		maxStdoutBytes: 1 << 20,
		maxStderrBytes: 1 << 20,
		maxRecords:     10,
	})
	if err != nil {
		t.Fatalf("build process runner: %v", err)
	}
	request := providercli.Request{
		Version:      providercli.Version{Protocol: providercli.ProtocolName, Major: providercli.ProtocolMajor, Minor: providercli.ProtocolMinor},
		RequestID:    "custody-follow",
		AdapterID:    "a",
		Function:     providercli.FunctionFollowOutput,
		DeadlineAtMS: time.Now().Add(2 * time.Second).UnixMilli(),
		Budget:       providercli.Budget{MaxStdoutBytes: 1 << 20, MaxStderrBytes: 1 << 20, MaxRecords: 10},
		Target:       &providercli.Target{ResourceKind: protocol.ResourceSession, ProviderResourceKey: "provider-session"},
		Payload:      json.RawMessage(`{"max_bytes":1024,"max_lines":10}`),
	}
	err = runner.invokeStream(context.Background(), request, func(providercli.StreamFrame) error { return nil })
	if !errors.Is(err, context.DeadlineExceeded) {
		t.Fatalf("invoke stream error = %v, want deadline exceeded", err)
	}
	holderPID := waitForCustodyPID(t, pidPath)
	t.Cleanup(func() { _ = syscall.Kill(holderPID, syscall.SIGKILL) })
	waitForCustodyProcessExit(t, holderPID)
	if processHoldsPath(holderPID, heldPath) {
		t.Fatalf("holder process %d still has %s open after follow timeout", holderPID, heldPath)
	}
}

func waitForCustodyPID(t *testing.T, path string) int {
	t.Helper()
	deadline := time.Now().Add(2 * time.Second)
	for time.Now().Before(deadline) {
		document, err := os.ReadFile(path)
		if err == nil {
			pid, parseErr := strconv.Atoi(string(document))
			if parseErr == nil && pid > 0 {
				return pid
			}
		}
		time.Sleep(10 * time.Millisecond)
	}
	t.Fatalf("custody helper did not publish its PID at %s", path)
	return 0
}

func waitForCustodyProcessExit(t *testing.T, pid int) {
	t.Helper()
	deadline := time.Now().Add(2 * time.Second)
	for time.Now().Before(deadline) {
		err := syscall.Kill(pid, 0)
		if errors.Is(err, syscall.ESRCH) {
			return
		}
		time.Sleep(10 * time.Millisecond)
	}
	t.Fatalf("detached provider helper %d survived invocation cleanup", pid)
}

func processHoldsPath(pid int, path string) bool {
	entries, err := os.ReadDir(fmt.Sprintf("/proc/%d/fd", pid))
	if err != nil {
		return false
	}
	for _, entry := range entries {
		target, readErr := os.Readlink(fmt.Sprintf("/proc/%d/fd/%s", pid, entry.Name()))
		if readErr == nil && target == path {
			return true
		}
	}
	return false
}
