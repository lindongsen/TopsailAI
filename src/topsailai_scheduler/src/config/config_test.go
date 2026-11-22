package config

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

// TestLoadDefaults verifies that an empty environment yields a usable
// configuration, because a missing configuration must never prevent startup.
func TestLoadDefaults(t *testing.T) {
	cfg, err := Load()
	if err != nil {
		t.Fatalf("Load failed with an empty environment: %v", err)
	}

	if cfg.TasksRoot != DefaultTasksRoot {
		t.Errorf("expected tasks root %q, got %q", DefaultTasksRoot, cfg.TasksRoot)
	}
	if cfg.LogLevel != DefaultLogLevel {
		t.Errorf("expected log level %q, got %q", DefaultLogLevel, cfg.LogLevel)
	}
	if cfg.MaxConcurrent != DefaultMaxConcurrent {
		t.Errorf("expected max concurrent %d, got %d", DefaultMaxConcurrent, cfg.MaxConcurrent)
	}
	if cfg.DefaultTimeout != DefaultTimeout {
		t.Errorf("expected default timeout %v, got %v", DefaultTimeout, cfg.DefaultTimeout)
	}
	if cfg.RescanInterval != DefaultRescanInterval {
		t.Errorf("expected rescan interval %v, got %v", DefaultRescanInterval, cfg.RescanInterval)
	}
	// The default socket is anchored to the home directory so every daemon on
	// this machine agrees on one path, which is what makes the single-instance
	// guard effective.
	home, err := os.UserHomeDir()
	if err != nil {
		t.Fatalf("resolve home directory: %v", err)
	}
	wantSocket := filepath.Join(home, DefaultControlSocketDir, DefaultControlSocketName)
	if cfg.ControlSocket != wantSocket {
		t.Errorf("expected control socket %q, got %q", wantSocket, cfg.ControlSocket)
	}
	if !filepath.IsAbs(cfg.ControlSocket) {
		t.Errorf("expected an absolute default control socket, got %q", cfg.ControlSocket)
	}
	if cfg.DefaultProviderPath != "" {
		t.Errorf("expected an empty default provider path, got %q", cfg.DefaultProviderPath)
	}
	if cfg.PollInterval != DefaultPollInterval {
		t.Errorf("expected poll interval %v, got %v", DefaultPollInterval, cfg.PollInterval)
	}
	if cfg.ProviderCallTimeout != DefaultProviderCallTimeout {
		t.Errorf("expected provider call timeout %v, got %v", DefaultProviderCallTimeout, cfg.ProviderCallTimeout)
	}
	if cfg.MinContentRunes != DefaultMinContentRunes {
		t.Errorf("expected min content runes %d, got %d", DefaultMinContentRunes, cfg.MinContentRunes)
	}
	if cfg.Workspace == "" {
		t.Error("expected the working directory as the default workspace")
	}
}

// TestDefaultMinContentRunesIsThirty pins the documented default. Without this
// the defaults test compares the loaded value against the constant itself, so
// changing the constant would keep both sides equal and go unnoticed.
func TestDefaultMinContentRunesIsThirty(t *testing.T) {
	if DefaultMinContentRunes != 30 {
		t.Fatalf("the documented default is 30, got %d", DefaultMinContentRunes)
	}
}

// TestLoadOverrides verifies that every documented variable is honoured.
func TestLoadOverrides(t *testing.T) {
	t.Setenv(EnvTasksRoot, "/custom/tasks")
	t.Setenv(EnvLogLevel, "debug")
	t.Setenv(EnvLogOutput, "/var/log/scheduler.log")
	t.Setenv(EnvLogMaxSizeMB, "5")
	t.Setenv(EnvLogMaxBackups, "3")
	t.Setenv(EnvLogMaxAgeDays, "7")
	t.Setenv(EnvLogCompress, "true")
	t.Setenv(EnvDefaultProviderPath, "/opt/providers/mock/bin/mock")
	t.Setenv(EnvWorkspace, "/work/demo")
	t.Setenv(EnvDefaultTimeout, "90s")
	t.Setenv(EnvMaxConcurrent, "8")
	t.Setenv(EnvRescanInterval, "5s")
	t.Setenv(EnvShutdownGrace, "10s")
	t.Setenv(EnvMaxOutputBytes, "2048")
	t.Setenv(EnvPollInterval, "2s")
	t.Setenv(EnvProviderCallTimeout, "15s")
	t.Setenv(EnvControlSocket, "/run/scheduler.sock")
	t.Setenv(EnvMinContentRunes, "45")

	cfg, err := Load()
	if err != nil {
		t.Fatalf("Load failed: %v", err)
	}
	checks := map[string]struct{ got, want any }{
		"tasks root":            {cfg.TasksRoot, "/custom/tasks"},
		"log level":             {cfg.LogLevel, "debug"},
		"log output":            {cfg.LogOutput, "/var/log/scheduler.log"},
		"log max size":          {cfg.LogMaxSizeMB, 5},
		"log max backups":       {cfg.LogMaxBackups, 3},
		"log max age":           {cfg.LogMaxAgeDays, 7},
		"log compress":          {cfg.LogCompress, true},
		"default provider path": {cfg.DefaultProviderPath, "/opt/providers/mock/bin/mock"},
		"workspace":             {cfg.Workspace, "/work/demo"},
		"timeout":               {cfg.DefaultTimeout, 90 * time.Second},
		"max concurrent":        {cfg.MaxConcurrent, 8},
		"rescan":                {cfg.RescanInterval, 5 * time.Second},
		"grace":                 {cfg.ShutdownGrace, 10 * time.Second},
		"max output":            {cfg.MaxOutputBytes, 2048},
		"poll interval":         {cfg.PollInterval, 2 * time.Second},
		"call timeout":          {cfg.ProviderCallTimeout, 15 * time.Second},
		"control socket":        {cfg.ControlSocket, "/run/scheduler.sock"},
		"min content runes":     {cfg.MinContentRunes, 45},
	}
	for name, check := range checks {
		if check.got != check.want {
			t.Errorf("%s: expected %v, got %v", name, check.want, check.got)
		}
	}
}

// TestLoadRejectsInvalidValues verifies that a present but invalid value is an
// error rather than a silent fallback, so a typo is not mistaken for a default.
func TestLoadRejectsInvalidValues(t *testing.T) {
	cases := map[string]struct{ name, value string }{
		"non-integer size":    {EnvLogMaxSizeMB, "big"},
		"non-integer backups": {EnvLogMaxBackups, "many"},
		"non-integer age":     {EnvLogMaxAgeDays, "old"},
		"non-integer slots":   {EnvMaxConcurrent, "lots"},
		"non-integer output":  {EnvMaxOutputBytes, "huge"},
		"non-boolean":         {EnvLogCompress, "yes-please"},
		"non-duration":        {EnvDefaultTimeout, "soon"},
		"bad rescan":          {EnvRescanInterval, "often"},
		"bad grace":           {EnvShutdownGrace, "later"},
		"non-integer runes":   {EnvMinContentRunes, "many"},
	}
	for name, testCase := range cases {
		t.Run(name, func(t *testing.T) {
			t.Setenv(testCase.name, testCase.value)
			if _, err := Load(); err == nil {
				t.Fatalf("expected %s=%q to be rejected", testCase.name, testCase.value)
			}
		})
	}
}

// TestValidateRejectsOutOfRange verifies the range checks that a valid parse can
// still violate.
func TestValidateRejectsOutOfRange(t *testing.T) {
	base := Config{
		TasksRoot:           "tasks",
		MaxConcurrent:       1,
		MaxOutputBytes:      1,
		DefaultTimeout:      time.Minute,
		RescanInterval:      time.Minute,
		ShutdownGrace:       0,
		ControlSocket:       "scheduler.sock",
		PollInterval:        time.Second,
		ProviderCallTimeout: time.Second,
	}

	cases := map[string]func(Config) Config{
		"empty tasks root":     func(c Config) Config { c.TasksRoot = " "; return c },
		"zero concurrency":     func(c Config) Config { c.MaxConcurrent = 0; return c },
		"zero output cap":      func(c Config) Config { c.MaxOutputBytes = 0; return c },
		"zero timeout":         func(c Config) Config { c.DefaultTimeout = 0; return c },
		"zero rescan":          func(c Config) Config { c.RescanInterval = 0; return c },
		"negative grace":       func(c Config) Config { c.ShutdownGrace = -time.Second; return c },
		"empty control socket": func(c Config) Config { c.ControlSocket = ""; return c },
		"zero poll interval":   func(c Config) Config { c.PollInterval = 0; return c },
		"zero call timeout":    func(c Config) Config { c.ProviderCallTimeout = 0; return c },
		"negative runes":       func(c Config) Config { c.MinContentRunes = -1; return c },
	}
	for name, mutate := range cases {
		t.Run(name, func(t *testing.T) {
			if err := mutate(base).Validate(); err == nil {
				t.Fatalf("expected %s to be rejected", name)
			}
		})
	}

	if err := base.Validate(); err != nil {
		t.Fatalf("expected the baseline configuration to be valid, got %v", err)
	}
}

// TestAbsoluteTasksRoot verifies that a relative root is resolved against the
// working directory and an absolute one is cleaned.
func TestAbsoluteTasksRoot(t *testing.T) {
	relative, err := Config{TasksRoot: "tasks"}.AbsoluteTasksRoot()
	if err != nil {
		t.Fatalf("resolve relative root: %v", err)
	}
	if !filepath.IsAbs(relative) {
		t.Errorf("expected an absolute path, got %q", relative)
	}
	if !strings.HasSuffix(relative, "tasks") {
		t.Errorf("expected the path to end with tasks, got %q", relative)
	}

	absolute, err := Config{TasksRoot: "/data/tasks/"}.AbsoluteTasksRoot()
	if err != nil {
		t.Fatalf("resolve absolute root: %v", err)
	}
	if absolute != "/data/tasks" {
		t.Errorf("expected a cleaned absolute path, got %q", absolute)
	}
}

// TestAbsoluteControlSocket verifies that a relative socket path follows the
// project it belongs to instead of becoming a global path.
func TestAbsoluteControlSocket(t *testing.T) {
	relative, err := Config{ControlSocket: "scheduler.sock"}.AbsoluteControlSocket()
	if err != nil {
		t.Fatalf("resolve relative socket: %v", err)
	}
	if !filepath.IsAbs(relative) {
		t.Errorf("expected an absolute path, got %q", relative)
	}

	absolute, err := Config{ControlSocket: "/run/scheduler.sock"}.AbsoluteControlSocket()
	if err != nil {
		t.Fatalf("resolve absolute socket: %v", err)
	}
	if absolute != "/run/scheduler.sock" {
		t.Errorf("expected the absolute path unchanged, got %q", absolute)
	}
}

// TestAbsoluteDefaultProviderPath verifies that a relative provider path follows
// the project it belongs to, so each project finds its own provider executable.
func TestAbsoluteDefaultProviderPath(t *testing.T) {
	relative, err := Config{DefaultProviderPath: "providers/mock/bin/mock"}.AbsoluteDefaultProviderPath()
	if err != nil {
		t.Fatalf("resolve relative provider path: %v", err)
	}
	if !filepath.IsAbs(relative) {
		t.Errorf("expected an absolute path, got %q", relative)
	}
	if !strings.HasSuffix(relative, filepath.Join("providers", "mock", "bin", "mock")) {
		t.Errorf("expected the path to end with the provider executable, got %q", relative)
	}

	absolute, err := Config{DefaultProviderPath: "/opt/providers/mock/bin/mock/"}.AbsoluteDefaultProviderPath()
	if err != nil {
		t.Fatalf("resolve absolute provider path: %v", err)
	}
	if absolute != "/opt/providers/mock/bin/mock" {
		t.Errorf("expected a cleaned absolute path, got %q", absolute)
	}
}
