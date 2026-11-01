// Package logging creates structured JSON loggers for Agent Cluster commands.
package logging

import (
	"io"
	"log/slog"
	"os"

	"gopkg.in/natefinch/lumberjack.v2"

	"topsailai_agent_cluster/internal/config"
)

// New creates a UTC JSON logger with bounded file rotation when configured.
func New(cfg config.Config) (*slog.Logger, io.Closer, error) {
	var writer io.Writer = os.Stderr
	var closer io.Closer = nopCloser{}
	if cfg.LogOutput == "file" {
		rotating := &lumberjack.Logger{Filename: cfg.LogPath, MaxSize: cfg.LogMaxSize, MaxBackups: cfg.LogBackups, MaxAge: cfg.LogMaxAge, Compress: true}
		writer = rotating
		closer = rotating
	}
	return slog.New(slog.NewJSONHandler(writer, &slog.HandlerOptions{AddSource: true})), closer, nil
}

type nopCloser struct{}

// Close releases the no-op logger resource.
func (nopCloser) Close() error { return nil }
