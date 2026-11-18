package client

import (
	"context"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync/atomic"
	"testing"
	"time"
)

// readyServer starts a Server that answers the readiness route with the given
// status and records every request it receives.
//
// The recorded requests are what let a test assert the probe's own shape, such as
// the absence of a credential, instead of only its outcome.
func readyServer(t *testing.T, status int) (*httptest.Server, *int32, *[]string) {
	t.Helper()
	var hits int32
	var paths []string
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		atomic.AddInt32(&hits, 1)
		paths = append(paths, r.URL.Path)
		if r.Header.Get("Authorization") != "" {
			// A probe that presents a credential is a defect, so it is reported as
			// a distinct status rather than silently accepted.
			w.WriteHeader(http.StatusTeapot)
			return
		}
		w.WriteHeader(status)
	}))
	t.Cleanup(server.Close)
	return server, &hits, &paths
}

// TestSelectProbeCarriesNoCredential asserts the security property the whole
// design rests on.
//
// HMAC is the default presentation mode, so a probe that carried a credential
// would sign a request with one Server's key and present it to a Server that has
// not been selected. The readiness route bypasses authentication, so the probe can
// be credential-free, and this test is the only evidence that it is.
func TestSelectProbeCarriesNoCredential(t *testing.T) {
	server, hits, paths := readyServer(t, http.StatusOK)
	selector := Selector{ProbeTimeout: time.Second}
	selection, err := selector.Select(context.Background(), []ServerCandidate{
		{Profile: "primary", URL: server.URL, Token: "key_id.secret"},
	})
	if err != nil {
		t.Fatalf("Select returned an error: %v", err)
	}
	if selection.Candidate.Profile != "primary" {
		t.Fatalf("selected profile = %q, want primary", selection.Candidate.Profile)
	}
	if got := atomic.LoadInt32(hits); got != 1 {
		t.Fatalf("probe count = %d, want 1", got)
	}
	if len(*paths) != 1 || (*paths)[0] != readinessPath {
		t.Fatalf("probed paths = %v, want [%s]", *paths, readinessPath)
	}
}

// TestSelectWalksInOrderUntilReady asserts that position expresses preference and
// that a not-ready Server is skipped rather than selected.
func TestSelectWalksInOrderUntilReady(t *testing.T) {
	notReady, notReadyHits, _ := readyServer(t, http.StatusServiceUnavailable)
	ready, readyHits, _ := readyServer(t, http.StatusOK)
	selector := Selector{ProbeTimeout: time.Second}
	selection, err := selector.Select(context.Background(), []ServerCandidate{
		{Profile: "primary", URL: notReady.URL},
		{Profile: "secondary", URL: ready.URL},
	})
	if err != nil {
		t.Fatalf("Select returned an error: %v", err)
	}
	if selection.Candidate.Profile != "secondary" {
		t.Fatalf("selected profile = %q, want secondary", selection.Candidate.Profile)
	}
	if got := atomic.LoadInt32(notReadyHits); got != 1 {
		t.Fatalf("primary probe count = %d, want 1", got)
	}
	if got := atomic.LoadInt32(readyHits); got != 1 {
		t.Fatalf("secondary probe count = %d, want 1", got)
	}
	if len(selection.Skipped) != 1 || selection.Skipped[0].Profile != "primary" {
		t.Fatalf("skipped = %+v, want one entry for primary", selection.Skipped)
	}
	if !strings.Contains(selection.Skipped[0].Reason, "not ready") {
		t.Fatalf("skip reason = %q, want it to name the not-ready answer", selection.Skipped[0].Reason)
	}
}

// TestSelectStopsOnRefusedCredential asserts that a credential problem is not
// disguised as a reachability problem.
//
// The second Server's probe count is the load-bearing assertion: falling back
// would present a second credential to a Server that already refused the first,
// and the operator would never learn that the credential is wrong.
func TestSelectStopsOnRefusedCredential(t *testing.T) {
	for _, status := range []int{http.StatusUnauthorized, http.StatusForbidden} {
		t.Run(http.StatusText(status), func(t *testing.T) {
			refusing, refusingHits, _ := readyServer(t, status)
			fallback, fallbackHits, _ := readyServer(t, http.StatusOK)
			selector := Selector{ProbeTimeout: time.Second}
			_, err := selector.Select(context.Background(), []ServerCandidate{
				{Profile: "primary", URL: refusing.URL},
				{Profile: "secondary", URL: fallback.URL},
			})
			if err == nil {
				t.Fatal("Select returned no error, want a credential refusal")
			}
			if !strings.Contains(err.Error(), "refused the credential") {
				t.Fatalf("error = %q, want it to name the credential refusal", err)
			}
			if got := atomic.LoadInt32(refusingHits); got != 1 {
				t.Fatalf("refusing probe count = %d, want 1", got)
			}
			if got := atomic.LoadInt32(fallbackHits); got != 0 {
				t.Fatalf("fallback probe count = %d, want 0: a credential refusal must not fall back", got)
			}
		})
	}
}

// TestSelectStopsOnOtherAnswer asserts that a healthy Server's answer is never
// replaced by a second Server's answer.
func TestSelectStopsOnOtherAnswer(t *testing.T) {
	answering, answeringHits, _ := readyServer(t, http.StatusInternalServerError)
	fallback, fallbackHits, _ := readyServer(t, http.StatusOK)
	selector := Selector{ProbeTimeout: time.Second}
	_, err := selector.Select(context.Background(), []ServerCandidate{
		{Profile: "primary", URL: answering.URL},
		{Profile: "secondary", URL: fallback.URL},
	})
	if err == nil {
		t.Fatal("Select returned no error, want the Server's own answer")
	}
	if !strings.Contains(err.Error(), "500") {
		t.Fatalf("error = %q, want it to name the status the Server answered", err)
	}
	if got := atomic.LoadInt32(answeringHits); got != 1 {
		t.Fatalf("answering probe count = %d, want 1", got)
	}
	if got := atomic.LoadInt32(fallbackHits); got != 0 {
		t.Fatalf("fallback probe count = %d, want 0: a real answer must not be replaced", got)
	}
}

// TestSelectSkipsUnreachableCandidate asserts that a transport failure is the one
// class that causes a switch.
func TestSelectSkipsUnreachableCandidate(t *testing.T) {
	closed := httptest.NewServer(http.HandlerFunc(func(http.ResponseWriter, *http.Request) {}))
	closedURL := closed.URL
	closed.Close()
	ready, readyHits, _ := readyServer(t, http.StatusOK)
	selector := Selector{ProbeTimeout: time.Second}
	selection, err := selector.Select(context.Background(), []ServerCandidate{
		{Profile: "primary", URL: closedURL},
		{Profile: "secondary", URL: ready.URL},
	})
	if err != nil {
		t.Fatalf("Select returned an error: %v", err)
	}
	if selection.Candidate.Profile != "secondary" {
		t.Fatalf("selected profile = %q, want secondary", selection.Candidate.Profile)
	}
	if got := atomic.LoadInt32(readyHits); got != 1 {
		t.Fatalf("secondary probe count = %d, want 1", got)
	}
	if len(selection.Skipped) != 1 || !strings.Contains(selection.Skipped[0].Reason, "unreachable") {
		t.Fatalf("skipped = %+v, want one unreachable entry", selection.Skipped)
	}
}

// TestSelectSkipsSlowCandidate asserts that one unresponsive Server cannot consume
// the whole attempt budget.
//
// Without a bounded probe, an address that accepts a connection and then never
// answers would hold the walk open until the caller's context expired, so the
// remaining candidates would never be tried.
func TestSelectSkipsSlowCandidate(t *testing.T) {
	slow := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		select {
		case <-time.After(2 * time.Second):
		case <-r.Context().Done():
		}
	}))
	t.Cleanup(slow.Close)
	ready, readyHits, _ := readyServer(t, http.StatusOK)
	selector := Selector{ProbeTimeout: 100 * time.Millisecond}
	started := time.Now()
	selection, err := selector.Select(context.Background(), []ServerCandidate{
		{Profile: "primary", URL: slow.URL},
		{Profile: "secondary", URL: ready.URL},
	})
	if err != nil {
		t.Fatalf("Select returned an error: %v", err)
	}
	if selection.Candidate.Profile != "secondary" {
		t.Fatalf("selected profile = %q, want secondary", selection.Candidate.Profile)
	}
	if elapsed := time.Since(started); elapsed > time.Second {
		t.Fatalf("walk took %s, want it bounded by the probe timeout", elapsed)
	}
	if got := atomic.LoadInt32(readyHits); got != 1 {
		t.Fatalf("secondary probe count = %d, want 1", got)
	}
}

// TestSelectNamesEveryCandidateWhenNoneReachable asserts that the failure names
// what was tried.
//
// The names are the only evidence that distinguishes "no Server is reachable" from
// "this Server refused me", and they are what lets an operator tell a single-Server
// outage from a fleet-wide one.
func TestSelectNamesEveryCandidateWhenNoneReachable(t *testing.T) {
	first := httptest.NewServer(http.HandlerFunc(func(http.ResponseWriter, *http.Request) {}))
	firstURL := first.URL
	first.Close()
	second := httptest.NewServer(http.HandlerFunc(func(http.ResponseWriter, *http.Request) {}))
	secondURL := second.URL
	second.Close()
	selector := Selector{ProbeTimeout: time.Second}
	_, err := selector.Select(context.Background(), []ServerCandidate{
		{Profile: "primary", URL: firstURL},
		{Profile: "secondary", URL: secondURL},
	})
	if err == nil {
		t.Fatal("Select returned no error, want an unreachable failure")
	}
	for _, want := range []string{"primary", "secondary", firstURL, secondURL} {
		if !strings.Contains(err.Error(), want) {
			t.Fatalf("error = %q, want it to name %q", err, want)
		}
	}
}

// TestSelectProbesSingleCandidate asserts that a group of one is still probed.
//
// This is not a behaviour change for an existing deployment: one candidate has
// nothing to fall back to, so a failed probe produces the same failure the request
// would have produced, reported with the same address.
func TestSelectProbesSingleCandidate(t *testing.T) {
	server, hits, _ := readyServer(t, http.StatusOK)
	selector := Selector{ProbeTimeout: time.Second}
	selection, err := selector.Select(context.Background(), []ServerCandidate{
		{Profile: "only", URL: server.URL},
	})
	if err != nil {
		t.Fatalf("Select returned an error: %v", err)
	}
	if selection.Candidate.Profile != "only" {
		t.Fatalf("selected profile = %q, want only", selection.Candidate.Profile)
	}
	if got := atomic.LoadInt32(hits); got != 1 {
		t.Fatalf("probe count = %d, want 1", got)
	}
	if len(selection.Skipped) != 0 {
		t.Fatalf("skipped = %+v, want none", selection.Skipped)
	}
}

// TestSelectRejectsEmptyCandidateList asserts that a missing configuration is
// reported as a configuration defect rather than as an unreachable Server.
func TestSelectRejectsEmptyCandidateList(t *testing.T) {
	selector := Selector{ProbeTimeout: time.Second}
	_, err := selector.Select(context.Background(), nil)
	if err == nil {
		t.Fatal("Select returned no error, want a configuration failure")
	}
	if !strings.Contains(err.Error(), "no Server is configured") {
		t.Fatalf("error = %q, want it to name the missing configuration", err)
	}
}

// TestSelectRejectsInvalidURL asserts that a local configuration defect stops the
// walk instead of being recorded as a skip.
//
// No other candidate can fix a malformed URL, so continuing would report a
// reachability problem for a configuration mistake.
func TestSelectRejectsInvalidURL(t *testing.T) {
	for _, address := range []string{"ftp://example.invalid", "://missing-scheme"} {
		t.Run(address, func(t *testing.T) {
			ready, readyHits, _ := readyServer(t, http.StatusOK)
			selector := Selector{ProbeTimeout: time.Second}
			_, err := selector.Select(context.Background(), []ServerCandidate{
				{Profile: "broken", URL: address},
				{Profile: "secondary", URL: ready.URL},
			})
			if err == nil {
				t.Fatal("Select returned no error, want a configuration failure")
			}
			if got := atomic.LoadInt32(readyHits); got != 0 {
				t.Fatalf("secondary probe count = %d, want 0: a configuration defect must stop the walk", got)
			}
		})
	}
}

// TestSelectHonoursCallerCancellation asserts that the caller's own cancellation is
// reported as an error rather than recorded as a Server being unreachable.
//
// A cancelled invocation says nothing about the candidate, so recording it as a
// skip would blame the Server for the caller's decision.
func TestSelectHonoursCallerCancellation(t *testing.T) {
	slow := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		select {
		case <-time.After(2 * time.Second):
		case <-r.Context().Done():
		}
	}))
	t.Cleanup(slow.Close)
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	selector := Selector{ProbeTimeout: time.Second}
	_, err := selector.Select(ctx, []ServerCandidate{{Profile: "primary", URL: slow.URL}})
	if err == nil {
		t.Fatal("Select returned no error, want the caller's cancellation")
	}
	if !strings.Contains(err.Error(), "context canceled") {
		t.Fatalf("error = %q, want the caller's cancellation", err)
	}
}
