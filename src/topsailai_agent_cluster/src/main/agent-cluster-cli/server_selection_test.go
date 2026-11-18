package main

import (
	"bytes"
	"context"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"topsailai_agent_cluster/internal/client"
)

// selectionServer starts a Server that answers the readiness route with status and
// counts every request it receives.
func selectionServer(t *testing.T, status int) (*httptest.Server, *int32) {
	t.Helper()
	var hits int32
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		atomic.AddInt32(&hits, 1)
		w.WriteHeader(status)
	}))
	t.Cleanup(server.Close)
	return server, &hits
}

// TestSelectServerTargetSingleCandidateIsSilentAndUnprobed asserts that an
// existing deployment is unchanged.
//
// One candidate has nothing to fall back to, so a probe could only add a failure
// mode and a diagnostic line to a configuration that already works. It also must
// not write sticky state, because there is no choice to remember.
func TestSelectServerTargetSingleCandidateIsSilentAndUnprobed(t *testing.T) {
	server, hits := selectionServer(t, http.StatusOK)
	stickyPath := filepath.Join(t.TempDir(), "server-profile")
	var diagnostics bytes.Buffer
	target, err := selectServerTarget(context.Background(), []ServerTarget{
		{Profile: "only", URL: server.URL, Token: "token"},
	}, stickyPath, client.Selector{ProbeTimeout: time.Second}, &diagnostics)
	if err != nil {
		t.Fatalf("selectServerTarget returned an error: %v", err)
	}
	if target.Profile != "only" || target.URL != server.URL || target.Token != "token" {
		t.Fatalf("target = %+v, want the single candidate unchanged", target)
	}
	if got := atomic.LoadInt32(hits); got != 0 {
		t.Fatalf("probe count = %d, want 0: a single candidate must not be probed", got)
	}
	if diagnostics.Len() != 0 {
		t.Fatalf("diagnostics = %q, want silence", diagnostics.String())
	}
	if _, err := os.Stat(stickyPath); !os.IsNotExist(err) {
		t.Fatalf("sticky file exists after a single-candidate selection: %v", err)
	}
}

// TestSelectServerTargetReportsSkipsAndChoice asserts that a successful walk is
// visible.
//
// Without the report the operator could not tell "the first Server is down" from
// "the first Server was never configured".
func TestSelectServerTargetReportsSkipsAndChoice(t *testing.T) {
	down, _ := selectionServer(t, http.StatusServiceUnavailable)
	up, _ := selectionServer(t, http.StatusOK)
	stickyPath := filepath.Join(t.TempDir(), "server-profile")
	var diagnostics bytes.Buffer
	target, err := selectServerTarget(context.Background(), []ServerTarget{
		{Profile: "primary", URL: down.URL},
		{Profile: "secondary", URL: up.URL},
	}, stickyPath, client.Selector{ProbeTimeout: time.Second}, &diagnostics)
	if err != nil {
		t.Fatalf("selectServerTarget returned an error: %v", err)
	}
	if target.Profile != "secondary" {
		t.Fatalf("target profile = %q, want secondary", target.Profile)
	}
	report := diagnostics.String()
	for _, want := range []string{`server "primary" skipped`, `using server profile "secondary"`} {
		if !strings.Contains(report, want) {
			t.Fatalf("diagnostics = %q, want it to contain %q", report, want)
		}
	}
	if got := readStickyProfile(stickyPath); got != "secondary" {
		t.Fatalf("sticky profile = %q, want secondary", got)
	}
}

// TestSelectServerTargetKeepsRememberedServer asserts the property that keeps the
// CLI in the same world as the fleet.
//
// The primary is healthy again, but the fleet is still on the secondary because an
// Endpoint only reconnects on transport failure. Returning to the primary would
// report an empty fleet, which reads as a total outage.
func TestSelectServerTargetKeepsRememberedServer(t *testing.T) {
	primary, primaryHits := selectionServer(t, http.StatusOK)
	secondary, secondaryHits := selectionServer(t, http.StatusOK)
	stickyPath := filepath.Join(t.TempDir(), "server-profile")
	if err := writeStickyProfile(stickyPath, "secondary"); err != nil {
		t.Fatalf("writeStickyProfile returned an error: %v", err)
	}
	var diagnostics bytes.Buffer
	target, err := selectServerTarget(context.Background(), []ServerTarget{
		{Profile: "primary", URL: primary.URL},
		{Profile: "secondary", URL: secondary.URL},
	}, stickyPath, client.Selector{ProbeTimeout: time.Second}, &diagnostics)
	if err != nil {
		t.Fatalf("selectServerTarget returned an error: %v", err)
	}
	if target.Profile != "secondary" {
		t.Fatalf("target profile = %q, want secondary: a recovered primary must not steal the CLI back", target.Profile)
	}
	if got := atomic.LoadInt32(secondaryHits); got != 1 {
		t.Fatalf("secondary probe count = %d, want 1", got)
	}
	if got := atomic.LoadInt32(primaryHits); got != 0 {
		t.Fatalf("primary probe count = %d, want 0: the remembered Server is tried first", got)
	}
}

// TestSelectServerTargetDoesNotRememberAFailedWalk asserts that a failed
// invocation never moves the preference.
//
// Recording a Server that was never reached would make the next run prefer a
// Server that is known to be down.
func TestSelectServerTargetDoesNotRememberAFailedWalk(t *testing.T) {
	first, _ := selectionServer(t, http.StatusServiceUnavailable)
	second, _ := selectionServer(t, http.StatusServiceUnavailable)
	stickyPath := filepath.Join(t.TempDir(), "server-profile")
	if err := writeStickyProfile(stickyPath, "primary"); err != nil {
		t.Fatalf("writeStickyProfile returned an error: %v", err)
	}
	var diagnostics bytes.Buffer
	_, err := selectServerTarget(context.Background(), []ServerTarget{
		{Profile: "primary", URL: first.URL},
		{Profile: "secondary", URL: second.URL},
	}, stickyPath, client.Selector{ProbeTimeout: time.Second}, &diagnostics)
	if err == nil {
		t.Fatal("selectServerTarget returned no error, want an unreachable failure")
	}
	if got := readStickyProfile(stickyPath); got != "primary" {
		t.Fatalf("sticky profile = %q, want primary unchanged", got)
	}
}

// TestSelectServerTargetReportsRetiredRememberedProfile asserts that a remembered
// name the operator has removed is reported rather than silently ignored.
//
// Silence would leave the operator believing a preference is in force when it is
// not.
func TestSelectServerTargetReportsRetiredRememberedProfile(t *testing.T) {
	first, _ := selectionServer(t, http.StatusOK)
	second, _ := selectionServer(t, http.StatusOK)
	stickyPath := filepath.Join(t.TempDir(), "server-profile")
	if err := writeStickyProfile(stickyPath, "retired"); err != nil {
		t.Fatalf("writeStickyProfile returned an error: %v", err)
	}
	var diagnostics bytes.Buffer
	target, err := selectServerTarget(context.Background(), []ServerTarget{
		{Profile: "primary", URL: first.URL},
		{Profile: "secondary", URL: second.URL},
	}, stickyPath, client.Selector{ProbeTimeout: time.Second}, &diagnostics)
	if err != nil {
		t.Fatalf("selectServerTarget returned an error: %v", err)
	}
	if target.Profile != "primary" {
		t.Fatalf("target profile = %q, want primary: the configured order decides", target.Profile)
	}
	if !strings.Contains(diagnostics.String(), `"retired" is no longer configured`) {
		t.Fatalf("diagnostics = %q, want it to name the retired profile", diagnostics.String())
	}
}

// TestSelectServerTargetRejectsEmptyList asserts that a missing configuration is
// reported as a configuration defect.
func TestSelectServerTargetRejectsEmptyList(t *testing.T) {
	_, err := selectServerTarget(context.Background(), nil, "", client.Selector{}, nil)
	if err == nil {
		t.Fatal("selectServerTarget returned no error, want a configuration failure")
	}
	if !strings.Contains(err.Error(), "no Server is configured") {
		t.Fatalf("error = %q, want it to name the missing configuration", err)
	}
}

// TestSelectServerTargetToleratesUnwritableStickyFile asserts that a preference
// file that cannot be written does not fail a working invocation.
//
// The request already succeeded; refusing to report that because a convenience
// file could not be written would turn a working command into a failure.
func TestSelectServerTargetToleratesUnwritableStickyFile(t *testing.T) {
	first, _ := selectionServer(t, http.StatusServiceUnavailable)
	second, _ := selectionServer(t, http.StatusOK)
	// A path whose parent is a regular file cannot be created.
	blocker := filepath.Join(t.TempDir(), "blocker")
	if err := os.WriteFile(blocker, []byte("x"), 0o600); err != nil {
		t.Fatalf("write blocker: %v", err)
	}
	stickyPath := filepath.Join(blocker, "server-profile")
	var diagnostics bytes.Buffer
	target, err := selectServerTarget(context.Background(), []ServerTarget{
		{Profile: "primary", URL: first.URL},
		{Profile: "secondary", URL: second.URL},
	}, stickyPath, client.Selector{ProbeTimeout: time.Second}, &diagnostics)
	if err != nil {
		t.Fatalf("selectServerTarget returned an error: %v", err)
	}
	if target.Profile != "secondary" {
		t.Fatalf("target profile = %q, want secondary", target.Profile)
	}
	if !strings.Contains(diagnostics.String(), "warning:") {
		t.Fatalf("diagnostics = %q, want a warning about the unwritable file", diagnostics.String())
	}
}
