package config

import (
	"testing"
)

// clearFileEnv removes the file-related environment variables so a test starts
// from the documented defaults.
func clearFileEnv(t *testing.T) {
	t.Helper()
	t.Setenv("HOME", t.TempDir())
	for _, key := range []string{
		EnvPrefix + "ROOT",
		EnvPrefix + "FILE_MAX_BYTES",
		EnvPrefix + "FILE_WHITE_LIST_NO_TRUNCATE_EXT",
	} {
		t.Setenv(key, "")
	}
}

func TestLoadFileMaxBytesDefault(t *testing.T) {
	clearFileEnv(t)

	cfg, err := Load()
	if err != nil {
		t.Fatalf("Load failed: %v", err)
	}
	if cfg.FileMaxBytes != DefaultFileMaxBytes {
		t.Fatalf("expected default file max bytes %d, got %d", DefaultFileMaxBytes, cfg.FileMaxBytes)
	}
	if len(cfg.FileNoTruncateExtensions) != 0 {
		t.Fatalf("expected no whitelist override by default, got %v", cfg.FileNoTruncateExtensions)
	}
}

func TestLoadFileMaxBytesFromEnv(t *testing.T) {
	clearFileEnv(t)
	t.Setenv(EnvPrefix+"FILE_MAX_BYTES", "1234")

	cfg, err := Load()
	if err != nil {
		t.Fatalf("Load failed: %v", err)
	}
	if cfg.FileMaxBytes != 1234 {
		t.Fatalf("expected file max bytes 1234, got %d", cfg.FileMaxBytes)
	}
}

func TestLoadFileMaxBytesRejectsInvalidValue(t *testing.T) {
	clearFileEnv(t)
	t.Setenv(EnvPrefix+"FILE_MAX_BYTES", "not-a-number")

	if _, err := Load(); err == nil {
		t.Fatal("expected an error for a non-numeric limit")
	}
}

func TestLoadFileMaxBytesRejectsNonPositiveValue(t *testing.T) {
	clearFileEnv(t)
	t.Setenv(EnvPrefix+"FILE_MAX_BYTES", "0")

	if _, err := Load(); err == nil {
		t.Fatal("expected an error for a zero limit")
	}
}

func TestLoadFileWhitelistFromEnv(t *testing.T) {
	clearFileEnv(t)
	t.Setenv(EnvPrefix+"FILE_WHITE_LIST_NO_TRUNCATE_EXT", " md , txt ,,log ")

	cfg, err := Load()
	if err != nil {
		t.Fatalf("Load failed: %v", err)
	}
	expected := []string{"md", "txt", "log"}
	if len(cfg.FileNoTruncateExtensions) != len(expected) {
		t.Fatalf("expected %v, got %v", expected, cfg.FileNoTruncateExtensions)
	}
	for i, want := range expected {
		if cfg.FileNoTruncateExtensions[i] != want {
			t.Fatalf("expected %v, got %v", expected, cfg.FileNoTruncateExtensions)
		}
	}
}

func TestValidateFillsFileMaxBytesDefault(t *testing.T) {
	cfg := &Config{
		Root:                t.TempDir(),
		MetadataAdapter:     "local",
		ActualDataAdapter:   "local",
		CeasedRetentionDays: DefaultCeasedRetentionDays,
		LogLevel:            DefaultLogLevel,
		StatFlush:           DefaultStatFlush,
	}

	if err := cfg.Validate(); err != nil {
		t.Fatalf("Validate failed: %v", err)
	}
	if cfg.FileMaxBytes != DefaultFileMaxBytes {
		t.Fatalf("expected Validate to fill the default limit, got %d", cfg.FileMaxBytes)
	}
}

func TestValidateRejectsNegativeFileMaxBytes(t *testing.T) {
	cfg := &Config{
		Root:                t.TempDir(),
		MetadataAdapter:     "local",
		ActualDataAdapter:   "local",
		CeasedRetentionDays: DefaultCeasedRetentionDays,
		LogLevel:            DefaultLogLevel,
		StatFlush:           DefaultStatFlush,
		FileMaxBytes:        -1,
	}

	if err := cfg.Validate(); err == nil {
		t.Fatal("expected an error for a negative limit")
	}
}
