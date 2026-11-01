package logging

import (
	"encoding/json"
	"os"
	"path/filepath"
	"testing"

	"topsailai_agent_cluster/internal/config"
)

func TestNewWritesJSONToFile(t *testing.T) {
	path := filepath.Join(t.TempDir(), "agent-cluster.log")
	logger, closer, err := New(config.Config{LogOutput: "file", LogPath: path, LogMaxSize: 1, LogBackups: 1})
	if err != nil {
		t.Fatalf("New returned error: %v", err)
	}
	logger.Info("test message", "module", "test", "trace_id", "trace")
	if err := closer.Close(); err != nil {
		t.Fatalf("Close returned error: %v", err)
	}
	content, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("ReadFile returned error: %v", err)
	}
	var entry map[string]any
	if err := json.Unmarshal(content, &entry); err != nil {
		t.Fatalf("log is not JSON: %v", err)
	}
	if entry["msg"] != "test message" || entry["module"] != "test" || entry["trace_id"] != "trace" {
		t.Fatalf("unexpected log entry: %v", entry)
	}
}
