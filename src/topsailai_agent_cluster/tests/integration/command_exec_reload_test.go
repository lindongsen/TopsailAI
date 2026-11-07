//go:build integration

package integration_test

import (
	"fmt"
	"os"
	"syscall"
	"testing"
	"time"
)

// TestCommandExecAllowlistReloadOnSIGHUP proves an operator can change the policy
// of a running Endpoint without restarting it.
//
// The reload is asserted in both directions: the newly listed command becomes
// permitted and the previously listed command becomes denied. Asserting only the
// addition would pass even if the reload appended entries instead of replacing
// them, which would leave a revoked command executable.
func TestCommandExecAllowlistReloadOnSIGHUP(t *testing.T) {
	c := startExecCluster(t, "pwd\n")
	defer c.stop(t)
	postExecCommand(t, c, "reload-before", []string{"pwd"})
	waitExecCommand(t, c, "reload-before", func(v execCommandView) bool { return v.Status == "finished" })

	if err := os.WriteFile(c.allowlist, []byte("echo\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := syscall.Kill(c.endpoint.Process.Pid, syscall.SIGHUP); err != nil {
		t.Fatalf("signal reload: %v", err)
	}

	// The reload is asynchronous, so a command admitted before the swap is denied
	// and cannot be retried under the same ID. Each attempt therefore uses a fresh
	// ID until one is admitted after the swap.
	waitExecPermitted(t, c, "reload-after", []string{"echo", "reloaded"})

	postExecCommand(t, c, "reload-revoked", []string{"pwd"})
	revoked := waitExecCommand(t, c, "reload-revoked", func(v execCommandView) bool { return v.Status == "rejected" })
	if revoked.EffectCertainty != "not_applied" || revoked.ErrorCode != "policy_denied" {
		t.Fatalf("expected the revoked command to be denied, got %+v", revoked)
	}
}

// waitExecPermitted retries one argv array under fresh command IDs until the
// Endpoint admits and completes it, which proves the reloaded policy is in force.
func waitExecPermitted(t *testing.T, c *execCluster, prefix string, argv []string) execCommandView {
	t.Helper()
	deadline := time.Now().Add(20 * time.Second)
	var last execCommandView
	for attempt := 0; time.Now().Before(deadline); attempt++ {
		id := fmt.Sprintf("%s-%d", prefix, attempt)
		postExecCommand(t, c, id, argv)
		view := waitExecCommand(t, c, id, func(v execCommandView) bool {
			return v.Status == "finished" || v.Status == "rejected"
		})
		if view.Status == "finished" {
			return view
		}
		last = view
		time.Sleep(200 * time.Millisecond)
	}
	t.Fatalf("command %v was never permitted after reload: %+v", argv, last)
	return last
}
