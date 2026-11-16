package main

import (
	"testing"
)

// inspectTarget builds the request shape the Cluster sends for one exact target.
func inspectTarget(key string) request {
	return request{
		RequestID: "req-inspect",
		Function:  functionInspect,
		Target:    &target{ProviderResourceKey: key},
	}
}

// TestInspectReportsAKnownLiveSessionAsLive pins the ordinary case.
//
// A session the mock publishes with a generation is running, so inspection must
// report it as found and live. Without this baseline the not-found case below
// could pass while inspection answered nothing at all.
func TestInspectReportsAKnownLiveSessionAsLive(t *testing.T) {
	response := handleUnary(inspectTarget("session:stable"), "", mockOptions{})
	if !response.OK {
		t.Fatalf("inspect rejected: %#v", response.Error)
	}
	if response.Inspection == nil {
		t.Fatal("inspect returned no inspection")
	}
	if !response.Inspection.Found {
		t.Fatal("a published session was reported as not found")
	}
	if !response.Inspection.Live {
		t.Fatal("a session with a generation was reported as not live")
	}
}

// TestInspectReportsAKnownStoppedSessionAsFoundButNotLive pins the resume case.
//
// The Cluster authorizes resume on the absence of a live target, so a stopped
// record must be found and not live. Reporting it as live would make resume
// unreachable; reporting it as not found would make the operator's own record
// invisible.
func TestInspectReportsAKnownStoppedSessionAsFoundButNotLive(t *testing.T) {
	response := handleUnary(inspectTarget("session:stopped"), "", mockOptions{})
	if !response.OK {
		t.Fatalf("inspect rejected: %#v", response.Error)
	}
	if response.Inspection == nil {
		t.Fatal("inspect returned no inspection")
	}
	if !response.Inspection.Found {
		t.Fatal("a published stopped session was reported as not found")
	}
	if response.Inspection.Live {
		t.Fatal("a stopped session was reported as live")
	}
}

// TestInspectReportsAnUnknownSessionAsNotFound pins the fidelity property the
// real provider already holds.
//
// The real provider scans its workspace rows and answers Found: false when no
// row matches. The mock used to answer every unknown target as found and live,
// so a resume by handle for a session that does not exist was refused with
// target_still_active. That told the operator the session was running when the
// truth was that no such session existed, which is the opposite of the real
// provider's answer and hides a mistyped handle behind a misleading refusal.
func TestInspectReportsAnUnknownSessionAsNotFound(t *testing.T) {
	response := handleUnary(inspectTarget("session:never-discovered"), "", mockOptions{})
	if !response.OK {
		t.Fatalf("inspect rejected: %#v", response.Error)
	}
	if response.Inspection == nil {
		t.Fatal("inspect returned no inspection")
	}
	if response.Inspection.Found {
		t.Fatal("an unpublished session was reported as found")
	}
	if response.Inspection.Live {
		t.Fatal("an unpublished session was reported as live")
	}
	if response.Inspection.Observation != nil {
		t.Fatal("an unpublished session carried an observation")
	}
}

// TestInspectReportsAMissingTargetAsNotFound pins the empty-target case.
//
// A request without a target names nothing, so it cannot be found. Answering it
// as live would let a malformed request authorize a resume.
func TestInspectReportsAMissingTargetAsNotFound(t *testing.T) {
	response := handleUnary(request{RequestID: "req-inspect", Function: functionInspect}, "", mockOptions{})
	if !response.OK {
		t.Fatalf("inspect rejected: %#v", response.Error)
	}
	if response.Inspection == nil {
		t.Fatal("inspect returned no inspection")
	}
	if response.Inspection.Found || response.Inspection.Live {
		t.Fatalf("a request without a target was reported as found=%t live=%t", response.Inspection.Found, response.Inspection.Live)
	}
}
