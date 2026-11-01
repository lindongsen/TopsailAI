package harness

import (
	"encoding/json"
	"strings"
	"testing"
)

// TestRunTUIExecutesWithoutTTY proves the harness builds and runs the real TUI subprocess.
func TestRunTUIExecutesWithoutTTY(t *testing.T) {
	cluster, err := StartCluster(t, ClusterOptions{})
	if err != nil {
		t.Fatal(err)
	}
	if _, err := cluster.BuildTUI(t); err != nil {
		t.Fatal(err)
	}
	stdout, stderr, exitCode, err := cluster.RunTUI("--json", "list")
	if err != nil {
		t.Fatalf("run TUI: %v; stderr=%s", err, stderr)
	}
	if exitCode != 0 {
		t.Fatalf("TUI exit code = %d; stderr=%s", exitCode, stderr)
	}
	var rows []map[string]any
	if err := json.Unmarshal([]byte(stdout), &rows); err != nil {
		t.Fatalf("decode TUI JSON: %v; stdout=%s", err, stdout)
	}
	if len(rows) == 0 || !strings.Contains(stdout, "endpoint-1") {
		t.Fatalf("TUI list did not include endpoint: %s", stdout)
	}
}
