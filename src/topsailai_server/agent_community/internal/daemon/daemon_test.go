package daemon

import (
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"syscall"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

// buildSleepyBinary builds the test helper binary and returns its path.
func buildSleepyBinary(t *testing.T) string {
	t.Helper()
	dst := filepath.Join(t.TempDir(), "sleepy")
	pkg := "github.com/topsailai/agent-community/internal/daemon/testdata/sleepy"
	cmd := exec.Command("go", "build", "-o", dst, pkg)
	cmd.Dir = "/TopsailAI/src/topsailai_server/agent_community"
	out, err := cmd.CombinedOutput()
	require.NoError(t, err, "failed to build sleepy binary: %s", string(out))
	return dst
}

func TestGetACSHome_Default(t *testing.T) {
	t.Setenv("TOPSAILAI_HOME", "")
	t.Setenv("ACS_HOME", "")
	assert.Equal(t, "/topsailai", getACSHome())
}

func TestGetACSHome_FromTOPSAILAI_HOME(t *testing.T) {
	t.Setenv("TOPSAILAI_HOME", "/custom/topsail")
	t.Setenv("ACS_HOME", "")
	assert.Equal(t, "/custom/topsail", getACSHome())
}

func TestGetLogPath(t *testing.T) {
	t.Setenv("TOPSAILAI_HOME", "/tmp/acs")
	assert.Equal(t, "/tmp/acs/log/agent_community.log", getLogPath())
}

func TestGetPIDPath(t *testing.T) {
	t.Setenv("TOPSAILAI_HOME", "/tmp/acs")
	assert.Equal(t, "/tmp/acs/run/agent_community.pid", getPIDPath())
}

func TestEnsureDir(t *testing.T) {
	dir := filepath.Join(t.TempDir(), "nested", "dir")
	require.NoError(t, ensureDir(dir))
	info, err := os.Stat(dir)
	require.NoError(t, err)
	assert.True(t, info.IsDir())
}

func TestWriteReadRemovePID(t *testing.T) {
	path := filepath.Join(t.TempDir(), "test.pid")

	// Write PID
	require.NoError(t, writePID(path))
	data, err := os.ReadFile(path)
	require.NoError(t, err)
	pid, err := strconv.Atoi(strings.TrimSpace(string(data)))
	require.NoError(t, err)
	assert.Equal(t, os.Getpid(), pid)

	// Read PID
	read, err := readPID(path)
	require.NoError(t, err)
	assert.Equal(t, os.Getpid(), read)

	// Remove PID
	require.NoError(t, removePID(path))
	_, err = os.Stat(path)
	assert.True(t, os.IsNotExist(err))

	// Remove non-existent PID should not error
	require.NoError(t, removePID(path))
}

func TestReadPID_InvalidContent(t *testing.T) {
	path := filepath.Join(t.TempDir(), "invalid.pid")
	require.NoError(t, os.WriteFile(path, []byte("not-a-number"), 0644))
	_, err := readPID(path)
	assert.Error(t, err)
}

func TestIsProcessRunning(t *testing.T) {
	// Current process must be running.
	assert.True(t, isProcessRunning(os.Getpid()))

	// Non-existent process should not be running.
	// PID 99999 is unlikely to exist on any test runner.
	assert.False(t, isProcessRunning(99999))
}

func TestStartWithExecutable_WritesPIDFile(t *testing.T) {
	home := t.TempDir()
	t.Setenv("TOPSAILAI_HOME", home)

	bin := buildSleepyBinary(t)
	require.NoError(t, StartWithExecutable(bin))

	// Give the helper a moment to set up its daemon environment.
	time.Sleep(200 * time.Millisecond)

	pidPath := getPIDPath()
	require.FileExists(t, pidPath)

	pid, err := readPID(pidPath)
	require.NoError(t, err)
	assert.True(t, isProcessRunning(pid), "helper process should be running")

	// Clean up
	require.NoError(t, Stop())
	assert.NoFileExists(t, pidPath)
}

func TestStartWithExecutable_AlreadyRunning(t *testing.T) {
	home := t.TempDir()
	t.Setenv("TOPSAILAI_HOME", home)

	bin := buildSleepyBinary(t)
	require.NoError(t, StartWithExecutable(bin))
	time.Sleep(200 * time.Millisecond)

	// Second start should fail because the process is already running.
	err := StartWithExecutable(bin)
	assert.Error(t, err)
	assert.Contains(t, err.Error(), "already running")

	require.NoError(t, Stop())
}

func TestStop_StalePID(t *testing.T) {
	home := t.TempDir()
	t.Setenv("TOPSAILAI_HOME", home)

	pidPath := getPIDPath()
	require.NoError(t, ensureDir(filepath.Dir(pidPath)))
	// Write a PID that does not exist.
	require.NoError(t, os.WriteFile(pidPath, []byte("99999\n"), 0644))

	err := Stop()
	assert.Error(t, err)
	assert.Contains(t, err.Error(), "not running")
	assert.NoFileExists(t, pidPath, "stale PID file should be removed")
}

func TestRestart(t *testing.T) {
	home := t.TempDir()
	t.Setenv("TOPSAILAI_HOME", home)

	bin := buildSleepyBinary(t)
	require.NoError(t, StartWithExecutable(bin))
	time.Sleep(200 * time.Millisecond)

	oldPID, err := readPID(getPIDPath())
	require.NoError(t, err)

	require.NoError(t, RestartWithExecutable(bin))
	time.Sleep(200 * time.Millisecond)

	newPID, err := readPID(getPIDPath())
	require.NoError(t, err)
	assert.NotEqual(t, oldPID, newPID, "restart should produce a new PID")
	assert.True(t, isProcessRunning(newPID), "new process should be running")

	require.NoError(t, Stop())
}

func TestStatus(t *testing.T) {
	home := t.TempDir()
	t.Setenv("TOPSAILAI_HOME", home)

	// No PID file: not running.
	status, err := Status()
	require.NoError(t, err)
	assert.False(t, status.Running)
	assert.Equal(t, 0, status.PID)

	// Start helper and verify running status.
	bin := buildSleepyBinary(t)
	require.NoError(t, StartWithExecutable(bin))
	time.Sleep(200 * time.Millisecond)

	status, err = Status()
	require.NoError(t, err)
	assert.True(t, status.Running)
	assert.Greater(t, status.PID, 0)

	require.NoError(t, Stop())

	// After stop: not running.
	status, err = Status()
	require.NoError(t, err)
	assert.False(t, status.Running)
}

func TestSetupDaemon_InSubprocess(t *testing.T) {
	// SetupDaemon redirects stdio, so we exercise it through the helper binary
	// which is started by StartWithExecutable in other tests. This test verifies
	// the log file is created when the helper runs.
	home := t.TempDir()
	t.Setenv("TOPSAILAI_HOME", home)

	bin := buildSleepyBinary(t)
	require.NoError(t, StartWithExecutable(bin))
	time.Sleep(200 * time.Millisecond)

	assert.FileExists(t, getLogPath())

	require.NoError(t, Stop())
}

func TestStop_Graceful(t *testing.T) {
	home := t.TempDir()
	t.Setenv("TOPSAILAI_HOME", home)

	bin := buildSleepyBinary(t)
	require.NoError(t, StartWithExecutable(bin))
	time.Sleep(200 * time.Millisecond)

	pid, err := readPID(getPIDPath())
	require.NoError(t, err)

	require.NoError(t, Stop())

	// Wait a bit and confirm the process is gone.
	time.Sleep(200 * time.Millisecond)
	assert.False(t, isProcessRunning(pid))
	assert.NoFileExists(t, getPIDPath())
}

func TestStop_ForceKill(t *testing.T) {
	// Start a process that ignores SIGTERM to exercise the force-kill path.
	home := t.TempDir()
	t.Setenv("TOPSAILAI_HOME", home)

	// Build a helper that ignores SIGTERM.
	src := `
package main
import (
	"os"
	"os/signal"
	"time"
)
func main() {
	sigCh := make(chan os.Signal, 1)
	signal.Notify(sigCh)
	time.Sleep(30 * time.Second)
}
`
	dst := filepath.Join(t.TempDir(), "stubborn")
	srcFile := filepath.Join(t.TempDir(), "stubborn.go")
	require.NoError(t, os.WriteFile(srcFile, []byte(src), 0644))
	cmd := exec.Command("go", "build", "-o", dst, srcFile)
	out, err := cmd.CombinedOutput()
	require.NoError(t, err, "failed to build stubborn binary: %s", string(out))

	// Start it and write its PID to the PID file.
	proc := exec.Command(dst)
	require.NoError(t, proc.Start())
	pid := proc.Process.Pid
	require.NoError(t, ensureDir(filepath.Dir(getPIDPath())))
	require.NoError(t, os.WriteFile(getPIDPath(), []byte(strconv.Itoa(pid)+"\n"), 0644))

	// Stop should eventually SIGKILL the process.
	require.NoError(t, Stop())

	// Reap the child process so it does not remain as a zombie.
	_, _ = proc.Process.Wait()

	// Confirm process is gone.
	time.Sleep(200 * time.Millisecond)
	assert.False(t, isProcessRunning(pid))
	assert.NoFileExists(t, getPIDPath())
}

// TestSignalCompatibility verifies that syscall.Signal(0) behaves as expected
// on the current platform. This is a sanity check for isProcessRunning.
func TestSignalCompatibility(t *testing.T) {
	err := syscall.Kill(os.Getpid(), syscall.Signal(0))
	assert.NoError(t, err)
}
