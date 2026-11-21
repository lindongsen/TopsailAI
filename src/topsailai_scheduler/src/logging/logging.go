// Package logging builds the structured JSON logger used by the scheduler.
//
// Every log entry is a single JSON object on one line. The handler always
// carries a module name so entries from different parts of the scheduler can be
// separated, and a trace id so all entries belonging to one task run can be
// correlated.
package logging

import (
	"fmt"
	"io"
	"log/slog"
	"os"
	"strings"

	"gopkg.in/natefinch/lumberjack.v2"
)

// Options describes where and how log entries are written.
type Options struct {
	// Level is one of debug, info, warn, error. Empty means info.
	Level string
	// Output is "stdout", "stderr", or a file path. Empty means stdout.
	Output string
	// MaxSizeMB is the size in megabytes that triggers a rotation.
	MaxSizeMB int
	// MaxBackups is the number of rotated files to keep.
	MaxBackups int
	// MaxAgeDays is the number of days a rotated file is kept.
	MaxAgeDays int
	// Compress gzips rotated files when true.
	Compress bool
}

// Default rotation values. They are deliberately small enough that a forgotten
// configuration cannot fill the disk, and large enough that a normal run does
// not rotate constantly.
const (
	DefaultMaxSizeMB  = 100
	DefaultMaxBackups = 10
	DefaultMaxAgeDays = 30
)

// New builds a JSON logger and returns a closer that must be closed on shutdown.
//
// The closer is a no-op for stdout and stderr output, so callers can always
// defer it without branching on the output kind.
func New(opts Options) (*slog.Logger, io.Closer, error) {
	level, err := parseLevel(opts.Level)
	if err != nil {
		return nil, nil, err
	}

	writer, closer, err := newWriter(opts)
	if err != nil {
		return nil, nil, err
	}

	handler := slog.NewJSONHandler(writer, &slog.HandlerOptions{
		Level: level,
		ReplaceAttr: func(groups []string, attr slog.Attr) slog.Attr {
			// slog writes time as RFC3339 with nanoseconds and a local offset.
			// Normalising to UTC keeps entries sortable across hosts.
			if attr.Key == slog.TimeKey && len(groups) == 0 {
				attr.Value = slog.TimeValue(attr.Value.Time().UTC())
			}
			return attr
		},
	})

	return slog.New(handler), closer, nil
}

// Module returns a logger tagged with the given module name.
func Module(logger *slog.Logger, name string) *slog.Logger {
	return logger.With(slog.String("module", name))
}

// WithTrace returns a logger tagged with a trace id, used to correlate every
// entry produced by one task run.
func WithTrace(logger *slog.Logger, traceID string) *slog.Logger {
	return logger.With(slog.String("trace_id", traceID))
}

// parseLevel converts a textual level into a slog level.
func parseLevel(text string) (slog.Level, error) {
	switch strings.ToLower(strings.TrimSpace(text)) {
	case "", "info":
		return slog.LevelInfo, nil
	case "debug":
		return slog.LevelDebug, nil
	case "warn", "warning":
		return slog.LevelWarn, nil
	case "error":
		return slog.LevelError, nil
	default:
		return 0, fmt.Errorf("invalid log level %q: want debug, info, warn or error", text)
	}
}

// newWriter selects the destination and applies rotation when it is a file.
func newWriter(opts Options) (io.Writer, io.Closer, error) {
	output := strings.TrimSpace(opts.Output)
	switch strings.ToLower(output) {
	case "", "stdout":
		return os.Stdout, nopCloser{}, nil
	case "stderr":
		return os.Stderr, nopCloser{}, nil
	}

	rotator := &lumberjack.Logger{
		Filename:   output,
		MaxSize:    positiveOr(opts.MaxSizeMB, DefaultMaxSizeMB),
		MaxBackups: positiveOr(opts.MaxBackups, DefaultMaxBackups),
		MaxAge:     positiveOr(opts.MaxAgeDays, DefaultMaxAgeDays),
		Compress:   opts.Compress,
	}
	return rotator, rotator, nil
}

// positiveOr returns value when it is positive, otherwise fallback.
func positiveOr(value, fallback int) int {
	if value > 0 {
		return value
	}
	return fallback
}

// nopCloser is the closer used for the standard streams.
type nopCloser struct{}

// Close does nothing.
func (nopCloser) Close() error { return nil }
