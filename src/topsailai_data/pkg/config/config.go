// Package config loads and validates topsailai_data configuration.
package config

import (
	"fmt"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"time"
)

const (
	// EnvPrefix is the prefix for all environment variables used by this project.
	EnvPrefix = "TOPSAILAI_DATA_"

	// DefaultCeasedRetentionDays is the default retention window for ceased metadata.
	DefaultCeasedRetentionDays = 30

	// DefaultLogLevel is the default log level.
	DefaultLogLevel = "INFO"
)

// Config holds the runtime configuration for topsailai_data.
type Config struct {
	// Root is the root directory for local storage adapters.
	Root string

	// MetadataAdapter is the name of the registered metadata adapter.
	MetadataAdapter string

	// ActualDataAdapter is the name of the registered actual-data adapter.
	ActualDataAdapter string

	// ReadLock indicates whether read operations should acquire advisory locks.
	ReadLock bool

	// IncludeDeleted indicates whether list/search operations include deleted/ceased objects.
	IncludeDeleted bool

	// CeasedRetentionDays is the number of days to retain ceased metadata before cleanup.
	CeasedRetentionDays int

	// LogLevel is the log level for the CLI.
	LogLevel string

	// AdapterConfig holds adapter-specific key-value settings.
	AdapterConfig map[string]string
}

// Load reads configuration from environment variables and optional .env files.
func Load() (*Config, error) {
	_ = loadDotEnv()

	cfg := &Config{
		Root:                os.Getenv(EnvPrefix + "ROOT"),
		MetadataAdapter:     os.Getenv(EnvPrefix + "METADATA_ADAPTER"),
		ActualDataAdapter:   os.Getenv(EnvPrefix + "ACTUAL_DATA_ADAPTER"),
		CeasedRetentionDays: DefaultCeasedRetentionDays,
		LogLevel:            DefaultLogLevel,
		AdapterConfig:       make(map[string]string),
	}

	if cfg.Root == "" {
		home, err := os.UserHomeDir()
		if err != nil {
			return nil, fmt.Errorf("cannot determine home directory for default %sROOT: %w", EnvPrefix, err)
		}
		cfg.Root = filepath.Join(home, ".topsailai", "data")
	}


	if cfg.MetadataAdapter == "" {
		cfg.MetadataAdapter = "local"
	}
	if cfg.ActualDataAdapter == "" {
		cfg.ActualDataAdapter = "local"
	}

	if v := os.Getenv(EnvPrefix + "READ_LOCK"); v != "" {
		cfg.ReadLock = parseBool(v)
	}
	if v := os.Getenv(EnvPrefix + "INCLUDE_DELETED"); v != "" {
		cfg.IncludeDeleted = parseBool(v)
	}
	if v := os.Getenv(EnvPrefix + "CEASED_RETENTION_DAYS"); v != "" {
		days, err := strconv.Atoi(v)
		if err != nil || days < 0 {
			return nil, fmt.Errorf("invalid %sCEASED_RETENTION_DAYS: %w", EnvPrefix, err)
		}
		cfg.CeasedRetentionDays = days
	}
	if v := os.Getenv(EnvPrefix + "LOG_LEVEL"); v != "" {
		cfg.LogLevel = strings.ToUpper(v)
	}

	for _, e := range os.Environ() {
		key, value, ok := strings.Cut(e, "=")
		if !ok {
			continue
		}
		if strings.HasPrefix(key, EnvPrefix+"ADAPTER_") {
			adapterKey := strings.TrimPrefix(key, EnvPrefix+"ADAPTER_")
			cfg.AdapterConfig[strings.ToLower(adapterKey)] = value
		}
	}

	if err := cfg.Validate(); err != nil {
		return nil, err
	}

	return cfg, nil
}

// Validate checks that the configuration is usable.
func (c *Config) Validate() error {
	if c.Root == "" {
		return fmt.Errorf("%sROOT is required", EnvPrefix)
	}
	absRoot, err := filepath.Abs(c.Root)
	if err != nil {
		return fmt.Errorf("invalid %sROOT: %w", EnvPrefix, err)
	}
	c.Root = absRoot

	if c.MetadataAdapter == "" {
		return fmt.Errorf("%sMETADATA_ADAPTER is required", EnvPrefix)
	}
	if c.ActualDataAdapter == "" {
		return fmt.Errorf("%sACTUAL_DATA_ADAPTER is required", EnvPrefix)
	}
	if c.CeasedRetentionDays < 0 {
		return fmt.Errorf("%sCEASED_RETENTION_DAYS must be non-negative", EnvPrefix)
	}
	return nil
}

// CeasedRetentionDuration returns the retention window as a time.Duration.
func (c *Config) CeasedRetentionDuration() time.Duration {
	return time.Duration(c.CeasedRetentionDays) * 24 * time.Hour
}

// loadDotEnv attempts to load .env and .env.local files from the working directory.
func loadDotEnv() error {
	for _, name := range []string{".env", ".env.local"} {
		if _, err := os.Stat(name); err == nil {
			data, err := os.ReadFile(name)
			if err != nil {
				return err
			}
			for _, line := range strings.Split(string(data), "\n") {
				line = strings.TrimSpace(line)
				if line == "" || strings.HasPrefix(line, "#") {
					continue
				}
				key, value, ok := strings.Cut(line, "=")
				if !ok {
					continue
				}
				if os.Getenv(key) == "" {
					os.Setenv(key, strings.Trim(value, `"'`))
				}
			}
		}
	}
	return nil
}

func parseBool(v string) bool {
	v = strings.ToLower(strings.TrimSpace(v))
	return v == "1" || v == "true" || v == "yes" || v == "on"
}
