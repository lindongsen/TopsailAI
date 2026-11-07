package harness

import (
	"net"
	"strconv"
	"strings"
	"testing"
	"time"
)

// TestServerReadinessWaitIsGenerous guards the flake repair. StartCluster waits
// for the Server health endpoint, and under full-parallel package load the
// machine runs several clusters at once. A regression to a tight budget would
// reintroduce the flaky failure, so the budget is asserted here.
func TestServerReadinessWaitIsGenerous(t *testing.T) {
	if serverReadinessWait < 30*time.Second {
		t.Fatalf("serverReadinessWait = %s, want at least 30s so a loaded machine can finish startup", serverReadinessWait)
	}
}

// TestWaitServerReadyReportsReadinessFailureContext verifies a readiness failure
// names the wait, so a failure is diagnosable without re-running the suite.
func TestWaitServerReadyReportsReadinessFailureContext(t *testing.T) {
	// A closed port makes the readiness wait expire immediately, which isolates
	// the error context from the real startup path.
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	port := listener.Addr().(*net.TCPAddr).Port
	if err := listener.Close(); err != nil {
		t.Fatal(err)
	}
	cluster := &Cluster{API: strconv.Itoa(port)}

	started := time.Now()
	waitErr := waitServerReady(cluster, 60*time.Millisecond)
	if waitErr == nil {
		t.Fatal("waitServerReady unexpectedly succeeded without a server")
	}
	if !strings.Contains(waitErr.Error(), "wait for server readiness") {
		t.Fatalf("error = %q, want readiness context", waitErr.Error())
	}
	if !strings.Contains(waitErr.Error(), "before deadline") {
		t.Fatalf("error = %q, want deadline context", waitErr.Error())
	}
	if elapsed := time.Since(started); elapsed > 3*time.Second {
		t.Fatalf("waitServerReady waited %s for a 60ms budget", elapsed)
	}
}
