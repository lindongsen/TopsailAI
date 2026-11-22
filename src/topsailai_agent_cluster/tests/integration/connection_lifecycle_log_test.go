//go:build integration

package integration_test

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"topsailai_agent_cluster/tests/harness"
)

// TestConnectionLifecycleLogsProveBothSides drives two real processes and
// asserts that each side records the connection lifecycle in its own log.
//
// The unit tests in internal/channel prove that the callbacks fire and that the
// Server writes the lines. They cannot prove the wiring in main.go, because that
// wiring is the process entry point: a unit test that calls Attach directly
// never runs it. This scenario is the only evidence that an operator reading a
// real Endpoint log after an outage can tell "started and connected" from
// "started, connected and later stopped", and that a Server log names the moment
// an Endpoint went offline.
//
// The failure this guards is the one that produced the original report: the
// Endpoint was upgraded, the process was absent for about a minute, and neither
// log contained a single line that could distinguish that from a network fault.
func TestConnectionLifecycleLogsProveBothSides(t *testing.T) {
	root := t.TempDir()
	serverLog := filepath.Join(root, "server.log")
	cluster, err := harness.StartCluster(t, harness.ClusterOptions{
		EndpointLogFile: true,
		// The Server log goes to a file so the scenario can read it back at the
		// exact moment it needs to. Environment is applied to the Server process
		// only, which is where these two settings belong.
		Environment: map[string]string{
			"AGENT_CLUSTER_LOG_OUTPUT": "file",
			"AGENT_CLUSTER_LOG_PATH":   serverLog,
		},
	})
	if err != nil {
		t.Fatalf("start cluster: %v", err)
	}
	t.Cleanup(func() { cluster.Stop(t) })

	// The first connection is the silent one: the reconnect path logs its own
	// success, so a scenario that only restarted the Endpoint would pass even
	// without the new callback. Asserting before any restart is what proves the
	// first adoption is reported.
	if err := cluster.WaitEndpointLogE("endpoint channel connected", 20*time.Second); err != nil {
		t.Fatalf("endpoint never logged its first connection: %v", err)
	}
	waitServerLogContains(t, serverLog, "endpoint online", 20*time.Second)

	// A restart is the case the operator hit. The Endpoint must say it shut down
	// deliberately, and the Server must say the Endpoint went offline, because
	// otherwise a clean stop and a crash look identical from both logs.
	cluster.RestartEndpoint(t)
	if err := cluster.WaitEndpointLogE("endpoint shutting down", 20*time.Second); err != nil {
		t.Fatalf("endpoint never logged its shutdown: %v", err)
	}
	waitServerLogContains(t, serverLog, "endpoint offline", 20*time.Second)

	// The restarted Endpoint must report its new connection too, so the log
	// contains a complete cycle rather than only the first adoption.
	if err := cluster.WaitEndpointLogE("endpoint channel connected", 20*time.Second); err != nil {
		t.Fatalf("restarted endpoint never logged its connection: %v", err)
	}
}

// waitServerLogContains polls a Server log file until it contains needle.
//
// The harness has no Server-log helper because no scenario needed one before:
// every previous assertion about Server behaviour went through the HTTP API. A
// log assertion cannot, so the polling lives here rather than in the harness,
// where it would be a single-use helper.
func waitServerLogContains(t *testing.T, path, needle string, limit time.Duration) {
	t.Helper()
	deadline := time.Now().Add(limit)
	var last string
	for time.Now().Before(deadline) {
		content, err := os.ReadFile(path)
		if err == nil {
			last = string(content)
			if strings.Contains(last, needle) {
				return
			}
		}
		time.Sleep(100 * time.Millisecond)
	}
	t.Fatalf("server log never contained %q within %s; log tail:\n%s", needle, limit, tailOf(last))
}

// tailOf returns the last 2000 bytes of a log so a failure shows recent context
// instead of the whole file.
func tailOf(content string) string {
	const limit = 2000
	if len(content) <= limit {
		return content
	}
	return content[len(content)-limit:]
}
