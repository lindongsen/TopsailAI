// Package logger provides JSON structured logging using the standard log/slog
// library with lumberjack for logrotate support.
package logger

import (
	"io"
	"os"

	"gopkg.in/natefinch/lumberjack.v2"
	"log/slog"
)

// iso8601UTCFormat is the ISO 8601 standard format in UTC.
const iso8601UTCFormat = "2006-01-02T15:04:05Z"

// Logger wraps slog.Logger to provide structured JSON logging.
type Logger struct {
	inner   *slog.Logger
	module  string
	traceID string
}

// Config holds logger initialization configuration.
type Config struct {
	Output     string
	Level      string
	FilePath   string
	MaxSize    int
	MaxAge     int
	MaxBackups int
}

// New creates a new Logger based on the provided configuration.
func New(cfg Config) *Logger {
	var output io.Writer
	switch cfg.Output {
	case "file":
		output = &lumberjack.Logger{
			Filename:   cfg.FilePath,
			MaxSize:    cfg.MaxSize,
			MaxAge:     cfg.MaxAge,
			MaxBackups: cfg.MaxBackups,
			Compress:   true,
			LocalTime:  false,
		}
	default:
		output = os.Stdout
	}
	return newWithWriter(cfg, output)
}

// newWithWriter creates a new Logger using the provided writer.
// It is unexported to allow tests to inject a buffer without touching real files or stdout.
func newWithWriter(cfg Config, output io.Writer) *Logger {
	level := parseLevel(cfg.Level)

	opts := &slog.HandlerOptions{
		Level:     level,
		AddSource: false,
		ReplaceAttr: func(groups []string, a slog.Attr) slog.Attr {
			if a.Key == slog.TimeKey {
				return slog.Attr{
					Key:   "timestamp",
					Value: slog.StringValue(a.Value.Time().UTC().Format(iso8601UTCFormat)),
				}
			}
			if a.Key == slog.LevelKey {
				return slog.Attr{
					Key:   "level",
					Value: slog.StringValue(a.Value.String()),
				}
			}
			if a.Key == slog.MessageKey {
				return slog.Attr{
					Key:   "message",
					Value: slog.StringValue(a.Value.String()),
				}
			}
			return a
		},
	}

	handler := slog.NewJSONHandler(output, opts)
	inner := slog.New(handler)

	return &Logger{inner: inner}
}

// parseLevel converts a string level to slog.Level.
func parseLevel(level string) slog.Level {
	switch level {
	case "debug":
		return slog.LevelDebug
	case "info":
		return slog.LevelInfo
	case "warn", "warning":
		return slog.LevelWarn
	case "error":
		return slog.LevelError
	default:
		return slog.LevelInfo
	}
}

// log is the internal helper that injects module and trace_id.
func (l *Logger) log(level slog.Level, module, traceID, msg string, args ...any) {
	if module == "" {
		module = l.module
	}
	if traceID == "" {
		traceID = l.traceID
	}
	attrs := []any{
		slog.String("module", module),
		slog.String("trace_id", traceID),
	}
	attrs = append(attrs, args...)

	switch level {
	case slog.LevelDebug:
		l.inner.Debug(msg, attrs...)
	case slog.LevelInfo:
		l.inner.Info(msg, attrs...)
	case slog.LevelWarn:
		l.inner.Warn(msg, attrs...)
	case slog.LevelError:
		l.inner.Error(msg, attrs...)
	}
}

// Debug logs a debug message.
func (l *Logger) Debug(module, traceID, msg string, args ...any) {
	l.log(slog.LevelDebug, module, traceID, msg, args...)
}

// Info logs an info message.
func (l *Logger) Info(module, traceID, msg string, args ...any) {
	l.log(slog.LevelInfo, module, traceID, msg, args...)
}

// Warn logs a warning message.
func (l *Logger) Warn(module, traceID, msg string, args ...any) {
	l.log(slog.LevelWarn, module, traceID, msg, args...)
}

// Error logs an error message.
func (l *Logger) Error(module, traceID, msg string, args ...any) {
	l.log(slog.LevelError, module, traceID, msg, args...)
}

// WithAttrs returns a new Logger with the given attributes pre-applied.
func (l *Logger) WithAttrs(module, traceID string) *Logger {
	return &Logger{
		inner:   l.inner,
		module:  module,
		traceID: traceID,
	}
}

// StdLogger returns the underlying slog.Logger for advanced use cases.
func (l *Logger) StdLogger() *slog.Logger {
	return l.inner
}

// defaultLogger is the package-level default logger instance.
var defaultLogger *Logger

// InitDefault initializes the package-level default logger.
func InitDefault(cfg Config) {
	defaultLogger = New(cfg)
}

// ensureDefault ensures the default logger is initialized.
func ensureDefault() {
	if defaultLogger == nil {
		defaultLogger = New(Config{Output: "stdout", Level: "info"})
	}
}

// Debug logs a debug message using the default logger.
func Debug(msg string, args ...any) {
	ensureDefault()
	defaultLogger.Debug("", "", msg, args...)
}

// Info logs an info message using the default logger.
func Info(msg string, args ...any) {
	ensureDefault()
	defaultLogger.Info("", "", msg, args...)
}

// Warn logs a warning message using the default logger.
func Warn(msg string, args ...any) {
	ensureDefault()
	defaultLogger.Warn("", "", msg, args...)
}

// Error logs an error message using the default logger.
func Error(msg string, args ...any) {
	ensureDefault()
	defaultLogger.Error("", "", msg, args...)
}

// DebugM logs a debug message with module and trace_id using the default logger.
func DebugM(module, traceID, msg string, args ...any) {
	ensureDefault()
	defaultLogger.Debug(module, traceID, msg, args...)
}

// InfoM logs an info message with module and trace_id using the default logger.
func InfoM(module, traceID, msg string, args ...any) {
	ensureDefault()
	defaultLogger.Info(module, traceID, msg, args...)
}

// WarnM logs a warning message with module and trace_id using the default logger.
func WarnM(module, traceID, msg string, args ...any) {
	ensureDefault()
	defaultLogger.Warn(module, traceID, msg, args...)
}

// ErrorM logs an error message with module and trace_id using the default logger.
func ErrorM(module, traceID, msg string, args ...any) {
	ensureDefault()
	defaultLogger.Error(module, traceID, msg, args...)
}
