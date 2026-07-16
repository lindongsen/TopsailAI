package config

import (
	"os"
	"path/filepath"
	"testing"
	"time"
)

func TestLoadDefaults(t *testing.T) {
	t.Setenv("HOME", t.TempDir())
	for _, key := range []string{
		EnvPrefix + "ROOT",
		EnvPrefix + "METADATA_ADAPTER",
		EnvPrefix + "ACTUAL_DATA_ADAPTER",
		EnvPrefix + "READ_LOCK",
		EnvPrefix + "INCLUDE_DELETED",
		EnvPrefix + "CEASED_RETENTION_DAYS",
		EnvPrefix + "LOG_LEVEL",
	} {
		t.Setenv(key, "")
	}

	cfg, err := Load()
	if err != nil {
		t.Fatalf("Load failed: %v", err)
	}

	if cfg.MetadataAdapter != "local" {
		t.Fatalf("expected default metadata adapter local, got %q", cfg.MetadataAdapter)
	}
	if cfg.ActualDataAdapter != "local" {
		t.Fatalf("expected default actual-data adapter local, got %q", cfg.ActualDataAdapter)
	}
	if cfg.CeasedRetentionDays != DefaultCeasedRetentionDays {
		t.Fatalf("expected default retention %d, got %d", DefaultCeasedRetentionDays, cfg.CeasedRetentionDays)
	}
	if cfg.LogLevel != DefaultLogLevel {
		t.Fatalf("expected default log level %q, got %q", DefaultLogLevel, cfg.LogLevel)
	}
	if cfg.ReadLock {
		t.Fatal("expected ReadLock to be false by default")
	}
	if cfg.IncludeDeleted {
		t.Fatal("expected IncludeDeleted to be false by default")
	}

	home, _ := os.UserHomeDir()
	wantRoot := filepath.Join(home, ".topsailai", "data")
	if cfg.Root != wantRoot {
		t.Fatalf("expected default root %q, got %q", wantRoot, cfg.Root)
	}
}

func TestLoadFromEnv(t *testing.T) {
	root := t.TempDir()
	t.Setenv(EnvPrefix+"ROOT", root)
	t.Setenv(EnvPrefix+"METADATA_ADAPTER", "postgres")
	t.Setenv(EnvPrefix+"ACTUAL_DATA_ADAPTER", "s3")
	t.Setenv(EnvPrefix+"READ_LOCK", "1")
	t.Setenv(EnvPrefix+"INCLUDE_DELETED", "true")
	t.Setenv(EnvPrefix+"CEASED_RETENTION_DAYS", "7")
	t.Setenv(EnvPrefix+"LOG_LEVEL", "debug")
	t.Setenv(EnvPrefix+"ADAPTER_BUCKET", "my-bucket")
	t.Setenv(EnvPrefix+"ADAPTER_DSN", "postgres://localhost")

	cfg, err := Load()
	if err != nil {
		t.Fatalf("Load failed: %v", err)
	}

	if cfg.Root != root {
		t.Fatalf("expected root %q, got %q", root, cfg.Root)
	}
	if cfg.MetadataAdapter != "postgres" {
		t.Fatalf("expected metadata adapter postgres, got %q", cfg.MetadataAdapter)
	}
	if cfg.ActualDataAdapter != "s3" {
		t.Fatalf("expected actual-data adapter s3, got %q", cfg.ActualDataAdapter)
	}
	if !cfg.ReadLock {
		t.Fatal("expected ReadLock to be true")
	}
	if !cfg.IncludeDeleted {
		t.Fatal("expected IncludeDeleted to be true")
	}
	if cfg.CeasedRetentionDays != 7 {
		t.Fatalf("expected retention 7, got %d", cfg.CeasedRetentionDays)
	}
	if cfg.LogLevel != "DEBUG" {
		t.Fatalf("expected log level DEBUG, got %q", cfg.LogLevel)
	}
	if cfg.AdapterConfig["bucket"] != "my-bucket" {
		t.Fatalf("expected adapter bucket my-bucket, got %q", cfg.AdapterConfig["bucket"])
	}
	if cfg.AdapterConfig["dsn"] != "postgres://localhost" {
		t.Fatalf("expected adapter dsn postgres://localhost, got %q", cfg.AdapterConfig["dsn"])
	}
}

func TestLoadInvalidCeasedRetentionDays(t *testing.T) {
	t.Setenv(EnvPrefix+"CEASED_RETENTION_DAYS", "not-a-number")

	_, err := Load()
	if err == nil {
		t.Fatal("expected error for invalid CEASED_RETENTION_DAYS")
	}
}

func TestLoadNegativeCeasedRetentionDays(t *testing.T) {
	t.Setenv(EnvPrefix+"CEASED_RETENTION_DAYS", "-1")

	_, err := Load()
	if err == nil {
		t.Fatal("expected error for negative CEASED_RETENTION_DAYS")
	}
}

func TestLoadDotEnv(t *testing.T) {
	tmp := t.TempDir()
	wd, err := os.Getwd()
	if err != nil {
		t.Fatalf("getwd: %v", err)
	}
	defer func() { _ = os.Chdir(wd) }()
	if err := os.Chdir(tmp); err != nil {
		t.Fatalf("chdir: %v", err)
	}

	if err := os.WriteFile(filepath.Join(tmp, ".env"), []byte("TOPSAILAI_DATA_LOG_LEVEL=warn\nTOPSAILAI_DATA_READ_LOCK=1\n"), 0o644); err != nil {
		t.Fatalf("write .env: %v", err)
	}

	cfg, err := Load()
	if err != nil {
		t.Fatalf("Load failed: %v", err)
	}
	if cfg.LogLevel != "WARN" {
		t.Fatalf("expected log level WARN from .env, got %q", cfg.LogLevel)
	}
	if !cfg.ReadLock {
		t.Fatal("expected ReadLock true from .env")
	}
}

func TestLoadDotEnvDoesNotOverrideExistingEnv(t *testing.T) {
	tmp := t.TempDir()
	wd, err := os.Getwd()
	if err != nil {
		t.Fatalf("getwd: %v", err)
	}
	defer func() { _ = os.Chdir(wd) }()
	if err := os.Chdir(tmp); err != nil {
		t.Fatalf("chdir: %v", err)
	}

	t.Setenv(EnvPrefix+"LOG_LEVEL", "ERROR")
	if err := os.WriteFile(filepath.Join(tmp, ".env"), []byte("TOPSAILAI_DATA_LOG_LEVEL=warn\n"), 0o644); err != nil {
		t.Fatalf("write .env: %v", err)
	}

	cfg, err := Load()
	if err != nil {
		t.Fatalf("Load failed: %v", err)
	}
	if cfg.LogLevel != "ERROR" {
		t.Fatalf("expected existing env to take precedence, got %q", cfg.LogLevel)
	}
}

func TestConfigValidate(t *testing.T) {
	cfg := &Config{
		Root:                t.TempDir(),
		MetadataAdapter:     "local",
		ActualDataAdapter:   "local",
		CeasedRetentionDays: 30,
	}
	if err := cfg.Validate(); err != nil {
		t.Fatalf("Validate failed: %v", err)
	}
	if !filepath.IsAbs(cfg.Root) {
		t.Fatalf("expected root to be absolute after validation, got %q", cfg.Root)
	}
}

func TestConfigValidateMissingRoot(t *testing.T) {
	cfg := &Config{
		Root:                "",
		MetadataAdapter:     "local",
		ActualDataAdapter:   "local",
		CeasedRetentionDays: 30,
	}
	if err := cfg.Validate(); err == nil {
		t.Fatal("expected error for missing root")
	}
}

func TestConfigValidateMissingAdapters(t *testing.T) {
	cfg := &Config{
		Root:                t.TempDir(),
		MetadataAdapter:     "",
		ActualDataAdapter:   "local",
		CeasedRetentionDays: 30,
	}
	if err := cfg.Validate(); err == nil {
		t.Fatal("expected error for missing metadata adapter")
	}

	cfg.MetadataAdapter = "local"
	cfg.ActualDataAdapter = ""
	if err := cfg.Validate(); err == nil {
		t.Fatal("expected error for missing actual-data adapter")
	}
}

func TestConfigValidateNegativeRetention(t *testing.T) {
	cfg := &Config{
		Root:                t.TempDir(),
		MetadataAdapter:     "local",
		ActualDataAdapter:   "local",
		CeasedRetentionDays: -1,
	}
	if err := cfg.Validate(); err == nil {
		t.Fatal("expected error for negative retention")
	}
}

func TestCeasedRetentionDuration(t *testing.T) {
	cfg := &Config{CeasedRetentionDays: 2}
	if got := cfg.CeasedRetentionDuration(); got != 48*time.Hour {
		t.Fatalf("expected 48h, got %v", got)
	}
}

func TestParseBool(t *testing.T) {
	cases := []struct {
		input string
		want  bool
	}{
		{"1", true},
		{"true", true},
		{"True", true},
		{"yes", true},
		{"on", true},
		{"0", false},
		{"false", false},
		{"no", false},
		{"off", false},
		{"", false},
		{"maybe", false},
	}

	for _, tc := range cases {
		t.Run(tc.input, func(t *testing.T) {
			if got := parseBool(tc.input); got != tc.want {
				t.Fatalf("parseBool(%q) = %v, want %v", tc.input, got, tc.want)
			}
		})
	}
}
