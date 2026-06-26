// Package daemon provides service management for the ACS server,
// including start, stop, and restart commands with PID file and log redirection.
package daemon

import (
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"syscall"
	"time"
)

const (
	defaultACSHome = "/topsailai"
	logFileName    = "agent_community.log"
	pidFileName    = "agent_community.pid"
)

// getACSHome returns the ACS_HOME directory.
// It checks ACS_HOME first, then TOPSAILAI_HOME, then falls back to /topsailai.
func getACSHome() string {
	if home := os.Getenv("ACS_HOME"); home != "" {
		return home
	}
	if home := os.Getenv("TOPSAILAI_HOME"); home != "" {
		return home
	}
	return defaultACSHome
}

// getLogPath returns the default log file path.
func getLogPath() string {
	return filepath.Join(getACSHome(), "log", logFileName)
}

// getPIDPath returns the default PID file path.
func getPIDPath() string {
	return filepath.Join(getACSHome(), "run", pidFileName)
}

// ensureDir creates the directory if it doesn't exist.
func ensureDir(dir string) error {
	if err := os.MkdirAll(dir, 0755); err != nil {
		return fmt.Errorf("failed to create directory %s: %w", dir, err)
	}
	return nil
}

// writePID writes the current process PID to the PID file.
func writePID(path string) error {
	if err := ensureDir(filepath.Dir(path)); err != nil {
		return err
	}
	pid := os.Getpid()
	if err := os.WriteFile(path, []byte(strconv.Itoa(pid)+"\n"), 0644); err != nil {
		return fmt.Errorf("failed to write PID file %s: %w", path, err)
	}
	return nil
}

// readPID reads the PID from the PID file.
func readPID(path string) (int, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return 0, fmt.Errorf("failed to read PID file %s: %w", path, err)
	}
	pidStr := strings.TrimSpace(string(data))
	pid, err := strconv.Atoi(pidStr)
	if err != nil {
		return 0, fmt.Errorf("invalid PID in file %s: %w", path, err)
	}
	return pid, nil
}

// removePID removes the PID file.
func removePID(path string) error {
	if err := os.Remove(path); err != nil && !os.IsNotExist(err) {
		return fmt.Errorf("failed to remove PID file %s: %w", path, err)
	}
	return nil
}

// isProcessRunning checks if a process with the given PID is running.
// On Linux it also treats zombie processes as not running so that Stop()
// does not wait indefinitely for an already-exited daemon child.
func isProcessRunning(pid int) bool {
	process, err := os.FindProcess(pid)
	if err != nil {
		return false
	}
	// On Unix systems, FindProcess always succeeds, so we need to send signal 0
	err = process.Signal(syscall.Signal(0))
	if err != nil {
		return false
	}
	// Zombie processes respond to signal 0 but are not really running.
	return !isZombie(pid)
}

// isZombie reports whether the process with the given PID is a zombie.
// It returns false on non-Linux platforms or if /proc cannot be read.
func isZombie(pid int) bool {
	data, err := os.ReadFile(fmt.Sprintf("/proc/%d/stat", pid))
	if err != nil {
		return false
	}
	// The process state is the third field. The command name (second field)
	// may contain spaces and parentheses, so we locate the last ')' and read
	// the character immediately after it.
	fields := strings.SplitN(string(data), ")", 2)
	if len(fields) < 2 {
		return false
	}
	parts := strings.Fields(fields[1])
	if len(parts) < 1 {
		return false
	}
	return parts[0] == "Z"
}

// SetupDaemon prepares the daemon environment: redirects logs and writes PID file.
// This should be called after the process has been forked to background.
func SetupDaemon() error {
	logPath := getLogPath()
	pidPath := getPIDPath()

	// Ensure log directory exists
	if err := ensureDir(filepath.Dir(logPath)); err != nil {
		return err
	}

	// Redirect stdout and stderr to log file
	logFile, err := os.OpenFile(logPath, os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0644)
	if err != nil {
		return fmt.Errorf("failed to open log file %s: %w", logPath, err)
	}
	defer logFile.Close()

	if err := redirectStdio(logFile); err != nil {
		return fmt.Errorf("failed to redirect stdio: %w", err)
	}

	// Write PID file
	if err := writePID(pidPath); err != nil {
		return err
	}

	return nil
}

// CleanupDaemon removes the PID file. Should be called on graceful shutdown.
func CleanupDaemon() error {
	return removePID(getPIDPath())
}

// Start starts the server in daemon mode.
// It forks a new process that runs in the background.
func Start() error {
	// Get the executable path
	exe, err := os.Executable()
	if err != nil {
		return fmt.Errorf("failed to get executable path: %w", err)
	}
	return StartWithExecutable(exe)
}

// StartWithExecutable starts the server in daemon mode using the provided executable path.
// It is exported for unit tests that need to start a helper binary instead of the real server.
func StartWithExecutable(exe string) error {
	pidPath := getPIDPath()

	// Check if already running
	if _, err := os.Stat(pidPath); err == nil {
		pid, err := readPID(pidPath)
		if err == nil && isProcessRunning(pid) {
			return fmt.Errorf("server is already running (PID: %d)", pid)
		}
		// PID file exists but process is not running, remove stale PID file
		_ = removePID(pidPath)
	}

	// Build command to run the server in daemon mode.
	// Preserve the parent's environment so ACS_HOME/TOPSAILAI_HOME are inherited.
	cmd := exec.Command(exe, "--daemon-internal")
	cmd.Stdout = nil
	cmd.Stderr = nil
	cmd.Stdin = nil
	cmd.Env = os.Environ()

	// Start the process
	if err := cmd.Start(); err != nil {
		return fmt.Errorf("failed to start daemon: %w", err)
	}

	fmt.Printf("Server started in background (PID: %d)\n", cmd.Process.Pid)
	fmt.Printf("Log file: %s\n", getLogPath())
	fmt.Printf("PID file: %s\n", pidPath)

	return nil
}

// Stop stops the running server by reading the PID file and killing the process.
func Stop() error {
	pidPath := getPIDPath()

	pid, err := readPID(pidPath)
	if err != nil {
		return err
	}

	if !isProcessRunning(pid) {
		_ = removePID(pidPath)
		return fmt.Errorf("server is not running (stale PID file removed)")
	}

	process, err := os.FindProcess(pid)
	if err != nil {
		return fmt.Errorf("failed to find process %d: %w", pid, err)
	}

	// Send SIGTERM for graceful shutdown
	if err := process.Signal(syscall.SIGTERM); err != nil {
		return fmt.Errorf("failed to send SIGTERM to process %d: %w", pid, err)
	}

	// Wait for process to exit with timeout
	for i := 0; i < 30; i++ {
		if !isProcessRunning(pid) {
			_ = removePID(pidPath)
			fmt.Printf("Server stopped (PID: %d)\n", pid)
			return nil
		}
		time.Sleep(500 * time.Millisecond)
	}

	// Force kill if still running
	_ = process.Signal(syscall.SIGKILL)
	_ = removePID(pidPath)
	fmt.Printf("Server force stopped (PID: %d)\n", pid)
	return nil
}

// Restart stops and then starts the server.
func Restart() error {
	// Get the executable path
	exe, err := os.Executable()
	if err != nil {
		return fmt.Errorf("failed to get executable path: %w", err)
	}
	return RestartWithExecutable(exe)
}

// RestartWithExecutable stops and then starts the server using the provided executable path.
// It is exported for unit tests that need to restart a helper binary instead of the real server.
func RestartWithExecutable(exe string) error {
	// Try to stop, but don't fail if not running
	pidPath := getPIDPath()
	if _, err := os.Stat(pidPath); err == nil {
		pid, err := readPID(pidPath)
		if err == nil && isProcessRunning(pid) {
			if err := Stop(); err != nil {
				return fmt.Errorf("failed to stop server: %w", err)
			}
		} else {
			_ = removePID(pidPath)
		}
	}

	// Small delay to ensure port is released
	time.Sleep(500 * time.Millisecond)

	return StartWithExecutable(exe)
}

// redirectStdio redirects stdout and stderr to the given file.
func redirectStdio(f *os.File) error {
	if err := syscall.Dup2(int(f.Fd()), int(os.Stdout.Fd())); err != nil {
		return err
	}
	if err := syscall.Dup2(int(f.Fd()), int(os.Stderr.Fd())); err != nil {
		return err
	}
	return nil
}

// GetLogPath returns the configured log file path.
func GetLogPath() string {
	return getLogPath()
}

// GetPIDPath returns the configured PID file path.
func GetPIDPath() string {
	return getPIDPath()
}

// GetACSHome returns the configured ACS_HOME directory.
func GetACSHome() string {
	return getACSHome()
}

// StatusResult holds the status information of the server.
type StatusResult struct {
	Running bool
	PID     int
	PIDPath string
	LogPath string
}

// Status checks the server status and returns a StatusResult.
func Status() (*StatusResult, error) {
	pidPath := getPIDPath()
	result := &StatusResult{
		Running: false,
		PID:     0,
		PIDPath: pidPath,
		LogPath: getLogPath(),
	}

	pid, err := readPID(pidPath)
	if err != nil {
		return result, nil
	}

	result.PID = pid
	result.Running = isProcessRunning(pid)

	return result, nil
}
