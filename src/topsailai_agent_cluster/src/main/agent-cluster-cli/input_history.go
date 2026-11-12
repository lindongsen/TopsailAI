package main

import (
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strconv"
	"strings"

	"topsailai_agent_cluster/internal/tui"
)

// Input history configuration names. They follow the Client section's bare
// AGENT_CLUSTER_ prefix rather than a CLI_ prefix, because these variables are
// read by the operator CLI and by nothing else, exactly like
// AGENT_CLUSTER_SERVER_URL. The bound names reuse the shape already used by the
// log rotation variables (MAX_SIZE_MB, MAX_BACKUPS), so one operator learns one
// set of spellings.
const (
	inputHistoryFileEnv       = "AGENT_CLUSTER_HISTORY_FILE"
	inputHistoryMaxEntriesEnv = "AGENT_CLUSTER_HISTORY_MAX_ENTRIES"
	inputHistoryMaxSizeMBEnv  = "AGENT_CLUSTER_HISTORY_MAX_SIZE_MB"
	inputHistoryMaxBackupsEnv = "AGENT_CLUSTER_HISTORY_MAX_BACKUPS"
)

// inputHistoryRelativePath is the default history file, placed beside the
// per-user configuration file the installer already writes. Keeping both under
// the same directory means one directory holds this operator's CLI state.
const inputHistoryRelativePath = ".topsailai/.topsailai_agent_cluster.history.jsonl"

// resolveInputHistory builds the input history store at the process boundary.
//
// Configuration is resolved here and passed down as a value, so no code below
// this point reads the environment. lookup is injected rather than read from the
// process, following loadEnvFile, so a test exercises the real resolution rules
// without mutating process-wide state.
//
// A malformed bound is rejected instead of silently replaced by its default,
// because an operator who wrote a value expects that value to be in force;
// falling back would leave the file growing past a bound the operator believes
// is set.
//
// An unresolvable home directory returns a nil store rather than an error.
// History is a convenience, and a CLI that refuses to start because it cannot
// name a file would be unusable for the reason it is least needed. A nil store
// keeps the previous in-memory behaviour, which is exactly what an operator
// without a home directory had before.
func resolveInputHistory(lookup func(string) string, home string, diagnostics io.Writer) (*tui.InputHistory, error) {
	path := resolveInputHistoryPath(lookup, home)
	if path == "" {
		return nil, nil
	}
	limits, err := resolveInputHistoryLimits(lookup)
	if err != nil {
		return nil, err
	}
	return tui.NewInputHistory(path, limits, diagnostics), nil
}

// resolveInputHistoryPath returns the configured file, or the per-user default.
// An empty result means no path could be resolved.
func resolveInputHistoryPath(lookup func(string) string, home string) string {
	if configured := strings.TrimSpace(lookup(inputHistoryFileEnv)); configured != "" {
		return configured
	}
	if strings.TrimSpace(home) == "" {
		return ""
	}
	return filepath.Join(home, filepath.FromSlash(inputHistoryRelativePath))
}

// resolveInputHistoryLimits reads the three bounds. An unset variable keeps the
// store's own default, so the defaults live in one place instead of being
// repeated here.
func resolveInputHistoryLimits(lookup func(string) string) (tui.InputHistoryLimits, error) {
	maxEntries, err := resolveInputHistoryInt(lookup, inputHistoryMaxEntriesEnv)
	if err != nil {
		return tui.InputHistoryLimits{}, err
	}
	maxSizeMB, err := resolveInputHistoryInt(lookup, inputHistoryMaxSizeMBEnv)
	if err != nil {
		return tui.InputHistoryLimits{}, err
	}
	maxBackups, err := resolveInputHistoryInt(lookup, inputHistoryMaxBackupsEnv)
	if err != nil {
		return tui.InputHistoryLimits{}, err
	}
	limits := tui.InputHistoryLimits{MaxEntries: maxEntries, MaxBackups: maxBackups}
	// The size bound is configured in megabytes and stored in bytes, so the
	// conversion happens once here rather than at every use.
	if maxSizeMB > 0 {
		limits.MaxSizeBytes = int64(maxSizeMB) << 20
	}
	return limits, nil
}

// resolveInputHistoryInt parses one bound. Zero means "unset" and is returned as
// zero so the store applies its default; a negative or unparsable value is an
// error, because neither can mean "unbounded" for an append-only file.
func resolveInputHistoryInt(lookup func(string) string, name string) (int, error) {
	raw := strings.TrimSpace(lookup(name))
	if raw == "" {
		return 0, nil
	}
	value, err := strconv.Atoi(raw)
	if err != nil {
		return 0, fmt.Errorf("%s=%q is not an integer", name, raw)
	}
	if value < 0 {
		return 0, fmt.Errorf("%s=%d must not be negative", name, value)
	}
	return value, nil
}

// resolveInputHistoryFromProcess is the shipped entry point. It reads the real
// environment and the real home directory once, so the resolution rules above
// stay testable while the binary still configures itself from its own process.
func resolveInputHistoryFromProcess(diagnostics io.Writer) (*tui.InputHistory, error) {
	home, err := os.UserHomeDir()
	if err != nil {
		// An unresolvable home directory only means the default path is absent.
		home = ""
	}
	return resolveInputHistory(os.Getenv, home, diagnostics)
}
