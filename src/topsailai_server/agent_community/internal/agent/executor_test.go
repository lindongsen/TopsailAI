package agent

import (
	"context"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func newTestExecutor() *Executor {
	return NewExecutor()
}

func newTestInterface(cmd string, timeout time.Duration) *Interface {
	return &Interface{
		Adaptor:            "test_adaptor",
		TimeoutCheckHealth: timeout,
		TimeoutCheckStatus: timeout,
		TimeoutChat:        timeout,
		CmdCheckHealth:     cmd,
		CmdCheckStatus:     cmd,
		CmdChat:            cmd,
	}
}

func TestExecutor_Execute_EmptyCommand(t *testing.T) {
	exec := newTestExecutor()

	_, err := exec.execute(context.Background(), "", nil, time.Second, "trace-1")
	if err == nil {
		t.Fatal("expected error for empty command")
	}
	if !strings.Contains(err.Error(), "command is empty") {
		t.Errorf("expected 'command is empty' error, got: %v", err)
	}
}

func TestExecutor_Execute_Success(t *testing.T) {
	exec := newTestExecutor()

	result, err := exec.execute(context.Background(), "echo hello", nil, time.Second, "trace-2")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if result.ExitCode != 0 {
		t.Errorf("exit code = %d, want 0", result.ExitCode)
	}
	if strings.TrimSpace(result.Stdout) != "hello" {
		t.Errorf("stdout = %q, want hello", result.Stdout)
	}
	if result.Duration < 0 {
		t.Errorf("duration = %d, want >= 0", result.Duration)
	}
}

func TestExecutor_Execute_NonZeroExit(t *testing.T) {
	exec := newTestExecutor()

	result, err := exec.execute(context.Background(), "exit 42", nil, time.Second, "trace-3")
	if err == nil {
		t.Fatal("expected error for non-zero exit")
	}
	if result.ExitCode != 42 {
		t.Errorf("exit code = %d, want 42", result.ExitCode)
	}
	if !strings.Contains(err.Error(), "command failed with exit code 42") {
		t.Errorf("expected exit code 42 in error, got: %v", err)
	}
}

func TestExecutor_Execute_Timeout(t *testing.T) {
	exec := newTestExecutor()
	start := time.Now()

	result, err := exec.execute(context.Background(), "sleep 5", nil, 50*time.Millisecond, "trace-4")
	elapsed := time.Since(start)

	if err == nil {
		t.Fatal("expected error for timeout")
	}
	if result.ExitCode != -1 {
		t.Errorf("exit code = %d, want -1", result.ExitCode)
	}
	if !strings.Contains(err.Error(), "timed out") {
		t.Errorf("expected timeout error, got: %v", err)
	}
	if elapsed >= time.Second {
		t.Errorf("timeout did not interrupt quickly: elapsed = %v, want < 1s", elapsed)
	}
}

func TestExecutor_Execute_ContextCancel(t *testing.T) {
	exec := newTestExecutor()
	ctx, cancel := context.WithCancel(context.Background())

	go func() {
		time.Sleep(50 * time.Millisecond)
		cancel()
	}()

	start := time.Now()
	result, err := exec.execute(ctx, "sleep 5", nil, time.Second, "trace-5")
	elapsed := time.Since(start)

	if err == nil {
		t.Fatal("expected error for cancelled context")
	}
	if result.ExitCode != -1 {
		t.Errorf("exit code = %d, want -1", result.ExitCode)
	}
	if !strings.Contains(err.Error(), "command failed with exit code -1") && !strings.Contains(err.Error(), "timed out") {
		t.Errorf("expected failure error, got: %v", err)
	}
	if elapsed >= time.Second {
		t.Errorf("cancel did not interrupt quickly: elapsed = %v, want < 1s", elapsed)
	}
}

func TestExecutor_Execute_EnvVars(t *testing.T) {
	exec := newTestExecutor()
	env := map[string]string{
		"ACS_TEST_VAR": "test_value",
	}

	result, err := exec.execute(context.Background(), "echo $ACS_TEST_VAR", env, time.Second, "trace-6")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if strings.TrimSpace(result.Stdout) != "test_value" {
		t.Errorf("stdout = %q, want test_value", result.Stdout)
	}
}

func TestExecutor_CheckHealth_EmptyCommand(t *testing.T) {
	exec := newTestExecutor()
	iface := newTestInterface("", time.Second)

	_, err := exec.CheckHealth(context.Background(), iface, nil, "trace-7")
	if err == nil {
		t.Fatal("expected error for empty health command")
	}
	if !strings.Contains(err.Error(), "command is empty") {
		t.Errorf("expected 'command is empty' error, got: %v", err)
	}
}

func TestExecutor_CheckStatus_SuccessAndFailure(t *testing.T) {
	exec := newTestExecutor()

	// Success case
	iface := newTestInterface("echo idle", time.Second)
	result, err := exec.CheckStatus(context.Background(), iface, nil, "trace-8")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	status, err := result.GetStatus()
	if err != nil {
		t.Fatalf("unexpected error getting status: %v", err)
	}
	if status != "idle" {
		t.Errorf("status = %q, want idle", status)
	}

	// Failure case
	iface = newTestInterface("exit 1", time.Second)
	result, err = exec.CheckStatus(context.Background(), iface, nil, "trace-9")
	if err == nil {
		t.Fatal("expected error for failed status check")
	}
	_, err = result.GetStatus()
	if err == nil {
		t.Fatal("expected error from GetStatus on failed result")
	}
}

func TestExecutor_Chat_Success(t *testing.T) {
	exec := newTestExecutor()
	iface := newTestInterface("echo response", time.Second)

	result, err := exec.Chat(context.Background(), iface, nil, "trace-10")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if result.ExitCode != 0 {
		t.Errorf("exit code = %d, want 0", result.ExitCode)
	}
	if strings.TrimSpace(result.Stdout) != "response" {
		t.Errorf("stdout = %q, want response", result.Stdout)
	}
}

func TestExecutionResult_IsHealthy(t *testing.T) {
	tests := []struct {
		name     string
		exitCode int
		want     bool
	}{
		{"zero exit", 0, true},
		{"non-zero exit", 1, false},
		{"timeout exit", -1, false},
		{"large non-zero", 255, false},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			result := &ExecutionResult{ExitCode: tt.exitCode}
			if got := result.IsHealthy(); got != tt.want {
				t.Errorf("IsHealthy() = %v, want %v", got, tt.want)
			}
		})
	}
}

func TestExecutionResult_GetStatus(t *testing.T) {
	tests := []struct {
		name      string
		stdout    string
		exitCode  int
		want      string
		wantError bool
	}{
		{"success with whitespace", "  idle  \n", 0, "idle", false},
		{"success no whitespace", "busy", 0, "busy", false},
		{"failure", "anything", 1, "", true},
		{"timeout", "anything", -1, "", true},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			result := &ExecutionResult{Stdout: tt.stdout, ExitCode: tt.exitCode}
			got, err := result.GetStatus()
			if (err != nil) != tt.wantError {
				t.Errorf("GetStatus() error = %v, wantError %v", err, tt.wantError)
				return
			}
			if got != tt.want {
				t.Errorf("GetStatus() = %q, want %q", got, tt.want)
			}
		})
	}
}

func TestResolveCommand_AbsolutePathUnchanged(t *testing.T) {
	exec := NewExecutorWithScriptsPath("/tmp")
	cmd := "/usr/bin/mock_agent_cmd_check_health"
	if got := exec.resolveCommand(cmd); got != cmd {
		t.Errorf("resolveCommand(%q) = %q, want unchanged", cmd, got)
	}
}

func TestResolveCommand_RelativeWithSeparatorUnchanged(t *testing.T) {
	exec := NewExecutorWithScriptsPath("/tmp")
	cmd := "./mock_agent_cmd_check_health"
	if got := exec.resolveCommand(cmd); got != cmd {
		t.Errorf("resolveCommand(%q) = %q, want unchanged", cmd, got)
	}
}

func TestResolveCommand_BareNameFoundInScriptsPath(t *testing.T) {
	tmpDir := t.TempDir()
	scriptPath := filepath.Join(tmpDir, "mock_agent_cmd_check_health")
	if err := os.WriteFile(scriptPath, []byte("#!/bin/sh\necho ok\n"), 0755); err != nil {
		t.Fatalf("failed to create test script: %v", err)
	}

	exec := NewExecutorWithScriptsPath(tmpDir)
	got := exec.resolveCommand("mock_agent_cmd_check_health")
	if got != scriptPath {
		t.Errorf("resolveCommand = %q, want %q", got, scriptPath)
	}
}

func TestResolveCommand_BareNameNotFoundFallsBack(t *testing.T) {
	exec := NewExecutorWithScriptsPath("/nonexistent/path")
	cmd := "mock_agent_cmd_check_health"
	if got := exec.resolveCommand(cmd); got != cmd {
		t.Errorf("resolveCommand(%q) = %q, want original command", cmd, got)
	}
}

func TestResolveCommand_FirstMatchWins(t *testing.T) {
	tmpDir1 := t.TempDir()
	tmpDir2 := t.TempDir()

	script1 := filepath.Join(tmpDir1, "mock_agent_cmd_check_health")
	script2 := filepath.Join(tmpDir2, "mock_agent_cmd_check_health")
	if err := os.WriteFile(script1, []byte("#!/bin/sh\necho first\n"), 0755); err != nil {
		t.Fatalf("failed to create test script: %v", err)
	}
	if err := os.WriteFile(script2, []byte("#!/bin/sh\necho second\n"), 0755); err != nil {
		t.Fatalf("failed to create test script: %v", err)
	}

	exec := NewExecutorWithScriptsPath(tmpDir1 + string(os.PathListSeparator) + tmpDir2)
	got := exec.resolveCommand("mock_agent_cmd_check_health")
	if got != script1 {
		t.Errorf("resolveCommand = %q, want %q", got, script1)
	}
}

func TestExecutor_Execute_ResolvedCommand(t *testing.T) {
	tmpDir := t.TempDir()
	scriptPath := filepath.Join(tmpDir, "mock_agent_cmd_chat")
	if err := os.WriteFile(scriptPath, []byte("#!/bin/sh\necho 'agent reply'\n"), 0755); err != nil {
		t.Fatalf("failed to create test script: %v", err)
	}

	exec := NewExecutorWithScriptsPath(tmpDir)
	result, err := exec.execute(context.Background(), "mock_agent_cmd_chat", nil, time.Second, "trace-resolved")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if strings.TrimSpace(result.Stdout) != "agent reply" {
		t.Errorf("stdout = %q, want 'agent reply'", result.Stdout)
	}
}
