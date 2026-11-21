// Package config loads the scheduler configuration from the process
// environment.
//
// Environment variables are read once, here at the boundary, and converted into
// a typed Config that is passed downward. Business logic never reads the
// environment directly, which keeps it testable and makes every knob visible in
// one place.
package config

import (
	"fmt"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"time"
)

// Environment variable names. They all carry the project prefix so they cannot
// collide with unrelated variables in the same shell.
const (
	EnvTasksRoot           = "SCHEDULER_TASKS_ROOT"
	EnvLogLevel            = "SCHEDULER_LOG_LEVEL"
	EnvLogOutput           = "SCHEDULER_LOG_OUTPUT"
	EnvLogMaxSizeMB        = "SCHEDULER_LOG_MAX_SIZE_MB"
	EnvLogMaxBackups       = "SCHEDULER_LOG_MAX_BACKUPS"
	EnvLogMaxAgeDays       = "SCHEDULER_LOG_MAX_AGE_DAYS"
	EnvLogCompress         = "SCHEDULER_LOG_COMPRESS"
	EnvWorkspace           = "SCHEDULER_WORKSPACE"
	EnvDefaultTimeout      = "SCHEDULER_DEFAULT_TIMEOUT"
	EnvMaxConcurrent       = "SCHEDULER_MAX_CONCURRENT"
	EnvRescanInterval      = "SCHEDULER_RESCAN_INTERVAL"
	EnvShutdownGrace       = "SCHEDULER_SHUTDOWN_GRACE"
	EnvMaxOutputBytes      = "SCHEDULER_MAX_OUTPUT_BYTES"
	EnvControlSocket       = "SCHEDULER_CONTROL_SOCKET"
	EnvDefaultProviderPath = "SCHEDULER_DEFAULT_PROVIDER_PATH"
	EnvPollInterval        = "SCHEDULER_POLL_INTERVAL"
	EnvProviderCallTimeout = "SCHEDULER_PROVIDER_CALL_TIMEOUT"
	EnvMinContentRunes     = "SCHEDULER_MIN_TASK_CONTENT_RUNES"
)

// Defaults chosen so the scheduler starts correctly with almost no
// configuration. The one required value is the default provider path, because a
// scheduler with no provider cannot run anything and guessing a location would
// hide a misconfiguration.
const (
	DefaultTasksRoot           = "tasks"
	DefaultLogLevel            = "info"
	DefaultLogOutput           = "stdout"
	DefaultLogMaxSizeMB        = 100
	DefaultLogMaxBackups       = 10
	DefaultLogMaxAgeDays       = 30
	DefaultTimeout             = 30 * time.Minute
	DefaultMaxConcurrent       = 4
	DefaultRescanInterval      = 30 * time.Second
	DefaultShutdownGrace       = 60 * time.Second
	DefaultMaxOutputBytes      = 64 * 1024
	DefaultPollInterval        = 5 * time.Second
	DefaultProviderCallTimeout = 30 * time.Second
	// DefaultMinContentRunes is the shortest task content accepted. A task
	// whose content is empty or a bare phrase gives an agent nothing to act
	// on, so it is rejected at load time instead of being scheduled and
	// failing on every trigger. Thirty characters is roughly one complete
	// instruction in Chinese and a short sentence in English.
	DefaultMinContentRunes = 30
	// DefaultControlSocket is resolved against the working directory, so each
	// project gets its own socket instead of sharing one global path.
	DefaultControlSocket = "scheduler.sock"
)

// Config is the complete scheduler configuration.
type Config struct {
	// TasksRoot is the folder tree scanned for task files.
	TasksRoot string
	// LogLevel is debug, info, warn or error.
	LogLevel string
	// LogOutput is stdout, stderr or a file path.
	LogOutput string
	// LogMaxSizeMB is the rotation size threshold.
	LogMaxSizeMB int
	// LogMaxBackups is the number of rotated files kept.
	LogMaxBackups int
	// LogMaxAgeDays is the retention age of rotated files.
	LogMaxAgeDays int
	// LogCompress gzips rotated files.
	LogCompress bool
	// Workspace is the default working directory for a run.
	Workspace string
	// DefaultTimeout bounds a run whose task sets no timeout.
	DefaultTimeout time.Duration
	// MaxConcurrent is the number of runs allowed at the same time.
	MaxConcurrent int
	// RescanInterval is how often the tasks tree is rescanned for changes.
	RescanInterval time.Duration
	// ShutdownGrace is how long running tasks get to finish on shutdown.
	ShutdownGrace time.Duration
	// MaxOutputBytes caps retained output per run.
	MaxOutputBytes int
	// ControlSocket is the Unix socket the CLI uses to reach the daemon.
	ControlSocket string
	// DefaultProviderPath is the executable of the provider used by a task that
	// names none. It is a path, not a name: a provider is an independent
	// program, so the scheduler must not assume where it lives.
	DefaultProviderPath string
	// PollInterval is how often a supervised run's state is checked.
	PollInterval time.Duration
	// ProviderCallTimeout bounds one provider protocol call.
	ProviderCallTimeout time.Duration
	// MinContentRunes is the shortest task content accepted, counted in runes
	// after trimming whitespace. It is a parameter rather than a constant in
	// the task package so a deployment can raise or lower the floor without a
	// rebuild.
	MinContentRunes int
}

// Load reads the configuration from the environment.
//
// Every value has a default, so an empty environment yields a usable
// configuration. A value that is present but invalid is an error rather than a
// silent fallback: a typo in a timeout must not be mistaken for the default.
func Load() (Config, error) {
	workingDir, err := os.Getwd()
	if err != nil {
		return Config{}, fmt.Errorf("resolve working directory: %w", err)
	}

	cfg := Config{
		TasksRoot:           DefaultTasksRoot,
		LogLevel:            DefaultLogLevel,
		LogOutput:           DefaultLogOutput,
		LogMaxSizeMB:        DefaultLogMaxSizeMB,
		LogMaxBackups:       DefaultLogMaxBackups,
		LogMaxAgeDays:       DefaultLogMaxAgeDays,
		Workspace:           workingDir,
		DefaultTimeout:      DefaultTimeout,
		MaxConcurrent:       DefaultMaxConcurrent,
		RescanInterval:      DefaultRescanInterval,
		ShutdownGrace:       DefaultShutdownGrace,
		MaxOutputBytes:      DefaultMaxOutputBytes,
		ControlSocket:       DefaultControlSocket,
		PollInterval:        DefaultPollInterval,
		ProviderCallTimeout: DefaultProviderCallTimeout,
		MinContentRunes:     DefaultMinContentRunes,
	}

	if value := strings.TrimSpace(os.Getenv(EnvTasksRoot)); value != "" {
		cfg.TasksRoot = value
	}
	if value := strings.TrimSpace(os.Getenv(EnvLogLevel)); value != "" {
		cfg.LogLevel = value
	}
	if value := strings.TrimSpace(os.Getenv(EnvLogOutput)); value != "" {
		cfg.LogOutput = value
	}
	if value := strings.TrimSpace(os.Getenv(EnvWorkspace)); value != "" {
		cfg.Workspace = value
	}
	if value := strings.TrimSpace(os.Getenv(EnvControlSocket)); value != "" {
		cfg.ControlSocket = value
	}
	if value := strings.TrimSpace(os.Getenv(EnvDefaultProviderPath)); value != "" {
		cfg.DefaultProviderPath = value
	}

	if cfg.LogMaxSizeMB, err = intFromEnv(EnvLogMaxSizeMB, cfg.LogMaxSizeMB); err != nil {
		return Config{}, err
	}
	if cfg.LogMaxBackups, err = intFromEnv(EnvLogMaxBackups, cfg.LogMaxBackups); err != nil {
		return Config{}, err
	}
	if cfg.LogMaxAgeDays, err = intFromEnv(EnvLogMaxAgeDays, cfg.LogMaxAgeDays); err != nil {
		return Config{}, err
	}
	if cfg.MaxConcurrent, err = intFromEnv(EnvMaxConcurrent, cfg.MaxConcurrent); err != nil {
		return Config{}, err
	}
	if cfg.MaxOutputBytes, err = intFromEnv(EnvMaxOutputBytes, cfg.MaxOutputBytes); err != nil {
		return Config{}, err
	}
	if cfg.LogCompress, err = boolFromEnv(EnvLogCompress, cfg.LogCompress); err != nil {
		return Config{}, err
	}
	if cfg.DefaultTimeout, err = durationFromEnv(EnvDefaultTimeout, cfg.DefaultTimeout); err != nil {
		return Config{}, err
	}
	if cfg.RescanInterval, err = durationFromEnv(EnvRescanInterval, cfg.RescanInterval); err != nil {
		return Config{}, err
	}
	if cfg.ShutdownGrace, err = durationFromEnv(EnvShutdownGrace, cfg.ShutdownGrace); err != nil {
		return Config{}, err
	}
	if cfg.PollInterval, err = durationFromEnv(EnvPollInterval, cfg.PollInterval); err != nil {
		return Config{}, err
	}
	if cfg.ProviderCallTimeout, err = durationFromEnv(EnvProviderCallTimeout, cfg.ProviderCallTimeout); err != nil {
		return Config{}, err
	}
	if cfg.MinContentRunes, err = intFromEnv(EnvMinContentRunes, cfg.MinContentRunes); err != nil {
		return Config{}, err
	}

	if err := cfg.Validate(); err != nil {
		return Config{}, err
	}
	return cfg, nil
}

// Validate rejects values that would make the scheduler misbehave.
func (c Config) Validate() error {
	if strings.TrimSpace(c.TasksRoot) == "" {
		return fmt.Errorf("%s must not be empty", EnvTasksRoot)
	}
	if c.MaxConcurrent < 1 {
		return fmt.Errorf("%s must be at least 1, got %d", EnvMaxConcurrent, c.MaxConcurrent)
	}
	if c.MaxOutputBytes < 1 {
		return fmt.Errorf("%s must be at least 1, got %d", EnvMaxOutputBytes, c.MaxOutputBytes)
	}
	if c.DefaultTimeout <= 0 {
		return fmt.Errorf("%s must be positive", EnvDefaultTimeout)
	}
	if c.RescanInterval <= 0 {
		return fmt.Errorf("%s must be positive", EnvRescanInterval)
	}
	if c.ShutdownGrace < 0 {
		return fmt.Errorf("%s must not be negative", EnvShutdownGrace)
	}
	if strings.TrimSpace(c.ControlSocket) == "" {
		return fmt.Errorf("%s must not be empty", EnvControlSocket)
	}
	if c.PollInterval <= 0 {
		return fmt.Errorf("%s must be positive", EnvPollInterval)
	}
	if c.ProviderCallTimeout <= 0 {
		return fmt.Errorf("%s must be positive", EnvProviderCallTimeout)
	}
	if c.MinContentRunes < 0 {
		return fmt.Errorf("%s must not be negative", EnvMinContentRunes)
	}
	return nil
}

// AbsoluteTasksRoot resolves the tasks root against the working directory.
func (c Config) AbsoluteTasksRoot() (string, error) {
	if filepath.IsAbs(c.TasksRoot) {
		return filepath.Clean(c.TasksRoot), nil
	}
	absolute, err := filepath.Abs(c.TasksRoot)
	if err != nil {
		return "", fmt.Errorf("resolve tasks root %q: %w", c.TasksRoot, err)
	}
	return absolute, nil
}

// AbsoluteControlSocket resolves the control socket against the working
// directory, so a relative socket path follows the project it belongs to.
func (c Config) AbsoluteControlSocket() (string, error) {
	if filepath.IsAbs(c.ControlSocket) {
		return filepath.Clean(c.ControlSocket), nil
	}
	absolute, err := filepath.Abs(c.ControlSocket)
	if err != nil {
		return "", fmt.Errorf("resolve control socket %q: %w", c.ControlSocket, err)
	}
	return absolute, nil
}

// AbsoluteDefaultProviderPath resolves the default provider executable against
// the working directory, so a relative value follows the project it belongs to.
func (c Config) AbsoluteDefaultProviderPath() (string, error) {
	if filepath.IsAbs(c.DefaultProviderPath) {
		return filepath.Clean(c.DefaultProviderPath), nil
	}
	absolute, err := filepath.Abs(c.DefaultProviderPath)
	if err != nil {
		return "", fmt.Errorf("resolve default provider path %q: %w", c.DefaultProviderPath, err)
	}
	return absolute, nil
}

// intFromEnv parses an integer variable, falling back to fallback when unset.
func intFromEnv(name string, fallback int) (int, error) {
	raw := strings.TrimSpace(os.Getenv(name))
	if raw == "" {
		return fallback, nil
	}
	value, err := strconv.Atoi(raw)
	if err != nil {
		return 0, fmt.Errorf("invalid %s=%q: want an integer", name, raw)
	}
	return value, nil
}

// boolFromEnv parses a boolean variable, falling back to fallback when unset.
func boolFromEnv(name string, fallback bool) (bool, error) {
	raw := strings.TrimSpace(os.Getenv(name))
	if raw == "" {
		return fallback, nil
	}
	value, err := strconv.ParseBool(raw)
	if err != nil {
		return false, fmt.Errorf("invalid %s=%q: want true or false", name, raw)
	}
	return value, nil
}

// durationFromEnv parses a duration variable, falling back to fallback when
// unset.
func durationFromEnv(name string, fallback time.Duration) (time.Duration, error) {
	raw := strings.TrimSpace(os.Getenv(name))
	if raw == "" {
		return fallback, nil
	}
	value, err := time.ParseDuration(raw)
	if err != nil {
		return 0, fmt.Errorf("invalid %s=%q: want a duration such as 30s or 5m", name, raw)
	}
	return value, nil
}
