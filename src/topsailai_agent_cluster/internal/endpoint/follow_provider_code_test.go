package endpoint

import (
	"context"
	"errors"
	"fmt"
	"testing"

	"topsailai_agent_cluster/internal/adapter"
	"topsailai_agent_cluster/internal/channel"
	"topsailai_agent_cluster/internal/protocol"
)

// TestStartFollowReportsProviderCancelledAsCancelled proves a Provider that
// reports its own cancellation ends the stream with "cancelled" rather than
// "provider_error".
//
// The Provider classifies the failure itself, so the Endpoint must not overwrite
// that classification. Reporting it as provider_error told the operator the
// Provider had failed when it had behaved correctly, and it hid the one fact that
// explains an empty tail: the stream was stopped rather than broken. This test
// fails when the Provider-code branch is removed, because the default branch then
// reports provider_error.
func TestStartFollowReportsProviderCancelledAsCancelled(t *testing.T) {
	executor := &followExecutor{followErr: &adapter.StreamError{Code: "cancelled", Message: "provider stopped the stream"}}
	service, transport := newFollowService(t, executor)
	service.startFollow(context.Background(), channel.Frame{Type: channel.FrameOutputFollowRequest, RequestID: "req-cancel", OutputFollowRequest: &protocol.OutputFollowRequest{ResourceID: "r"}})
	waitForFrames(t, transport, channel.FrameOutputEnd, 1)
	transport.mu.Lock()
	end := transport.frames[len(transport.frames)-1].OutputEnd
	transport.mu.Unlock()
	if end == nil || end.ErrorCode != "cancelled" {
		t.Fatalf("end=%#v want cancelled", end)
	}
}

// TestStartFollowReportsProviderUnsupportedAsUnsupported proves a Provider that
// reports it cannot tail the target keeps the capability answer instead of being
// reported as a fault.
func TestStartFollowReportsProviderUnsupportedAsUnsupported(t *testing.T) {
	executor := &followExecutor{followErr: &adapter.StreamError{Code: "unsupported", Message: "provider cannot tail"}}
	service, transport := newFollowService(t, executor)
	service.startFollow(context.Background(), channel.Frame{Type: channel.FrameOutputFollowRequest, RequestID: "req-unsup", OutputFollowRequest: &protocol.OutputFollowRequest{ResourceID: "r"}})
	waitForFrames(t, transport, channel.FrameOutputEnd, 1)
	transport.mu.Lock()
	end := transport.frames[len(transport.frames)-1].OutputEnd
	transport.mu.Unlock()
	if end == nil || end.ErrorCode != "unsupported" {
		t.Fatalf("end=%#v want unsupported", end)
	}
}

// TestStartFollowReportsProviderInvalidRequestAsInvalidRequest proves a Provider
// that rejects the request it was given is reported as a request fault rather
// than a Provider fault.
func TestStartFollowReportsProviderInvalidRequestAsInvalidRequest(t *testing.T) {
	executor := &followExecutor{followErr: &adapter.StreamError{Code: "invalid_request", Message: "provider rejected the request"}}
	service, transport := newFollowService(t, executor)
	service.startFollow(context.Background(), channel.Frame{Type: channel.FrameOutputFollowRequest, RequestID: "req-invalid", OutputFollowRequest: &protocol.OutputFollowRequest{ResourceID: "r"}})
	waitForFrames(t, transport, channel.FrameOutputEnd, 1)
	transport.mu.Lock()
	end := transport.frames[len(transport.frames)-1].OutputEnd
	transport.mu.Unlock()
	if end == nil || end.ErrorCode != "invalid_request" {
		t.Fatalf("end=%#v want invalid_request", end)
	}
}

// TestStartFollowKeepsProviderErrorForUnrecognisedCode proves an unrecognised
// Provider code still ends the stream with provider_error.
//
// The Cluster vocabulary is closed, so a Provider code the Endpoint does not
// recognise must not be forwarded as if it were part of that vocabulary. This
// test is the counterpart of the three above: without it, a change that forwarded
// every Provider code verbatim would pass them and silently widen the vocabulary.
func TestStartFollowKeepsProviderErrorForUnrecognisedCode(t *testing.T) {
	executor := &followExecutor{followErr: &adapter.StreamError{Code: "provider_specific_failure", Message: "provider failed"}}
	service, transport := newFollowService(t, executor)
	service.startFollow(context.Background(), channel.Frame{Type: channel.FrameOutputFollowRequest, RequestID: "req-unknown", OutputFollowRequest: &protocol.OutputFollowRequest{ResourceID: "r"}})
	waitForFrames(t, transport, channel.FrameOutputEnd, 1)
	transport.mu.Lock()
	end := transport.frames[len(transport.frames)-1].OutputEnd
	transport.mu.Unlock()
	if end == nil || end.ErrorCode != "provider_error" {
		t.Fatalf("end=%#v want provider_error", end)
	}
}

// TestProviderStreamCodeDistinguishesAbsentFromEmpty proves an absent code and an
// empty code are both reported as "no classification".
//
// The distinction matters because the caller falls back to its own sentinel
// checks when no code was found. Treating an empty code as a classification would
// make the fallback unreachable for a Provider that reported a failure without
// naming it.
func TestProviderStreamCodeDistinguishesAbsentFromEmpty(t *testing.T) {
	cases := []struct {
		name     string
		err      error
		wantCode string
		wantOK   bool
	}{
		{name: "absent", err: errors.New("plain failure"), wantCode: "", wantOK: false},
		{name: "empty", err: &adapter.StreamError{Message: "no code"}, wantCode: "", wantOK: false},
		{name: "present", err: &adapter.StreamError{Code: "cancelled", Message: "stopped"}, wantCode: "cancelled", wantOK: true},
		{name: "wrapped", err: errors.Join(errors.New("outer"), &adapter.StreamError{Code: "unsupported"}), wantCode: "unsupported", wantOK: true},
	}
	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			code, ok := providerStreamCode(testCase.err)
			if code != testCase.wantCode || ok != testCase.wantOK {
				t.Fatalf("code=%q ok=%v want code=%q ok=%v", code, ok, testCase.wantCode, testCase.wantOK)
			}
		})
	}
}

// TestStartFollowReportsBudgetExpiryAsFollowTimeout proves a stream that reaches
// its own budget ends with "follow_timeout" rather than "cancelled".
//
// The two facts are different and the remedy differs. A timeout means nobody
// stopped the stream and the operator may simply follow again; a cancellation
// means someone stopped it deliberately. Reporting both as "cancelled" sent the
// operator looking for whoever stopped the stream while the stream had only
// expired, which is exactly the symptom this code exists to name.
//
// The error is wrapped because the adapter wraps the context error with %w, so
// errors.Is must still see the sentinel through the wrapper. A test that passed a
// bare context.DeadlineExceeded would not prove the real path works.
func TestStartFollowReportsBudgetExpiryAsFollowTimeout(t *testing.T) {
	executor := &followExecutor{followErr: fmt.Errorf("provider stream: %w", context.DeadlineExceeded)}
	service, transport := newFollowService(t, executor)
	service.startFollow(context.Background(), channel.Frame{Type: channel.FrameOutputFollowRequest, RequestID: "req-timeout", OutputFollowRequest: &protocol.OutputFollowRequest{ResourceID: "r"}})
	waitForFrames(t, transport, channel.FrameOutputEnd, 1)
	transport.mu.Lock()
	end := transport.frames[len(transport.frames)-1].OutputEnd
	transport.mu.Unlock()
	if end == nil || end.ErrorCode != "follow_timeout" {
		t.Fatalf("end=%#v want follow_timeout", end)
	}
}

// TestStartFollowKeepsCancelledForRealCancellation proves a genuine cancellation
// still reports "cancelled" after the timeout branch was split out.
//
// Without this test the split could be implemented by mapping every context error
// to follow_timeout, which would misreport a deliberate stop as an expiry and send
// the operator to investigate a bound nobody reached.
func TestStartFollowKeepsCancelledForRealCancellation(t *testing.T) {
	executor := &followExecutor{followErr: fmt.Errorf("provider stream: %w", context.Canceled)}
	service, transport := newFollowService(t, executor)
	service.startFollow(context.Background(), channel.Frame{Type: channel.FrameOutputFollowRequest, RequestID: "req-real-cancel", OutputFollowRequest: &protocol.OutputFollowRequest{ResourceID: "r"}})
	waitForFrames(t, transport, channel.FrameOutputEnd, 1)
	transport.mu.Lock()
	end := transport.frames[len(transport.frames)-1].OutputEnd
	transport.mu.Unlock()
	if end == nil || end.ErrorCode != "cancelled" {
		t.Fatalf("end=%#v want cancelled", end)
	}
}

// TestStartFollowReportsProviderFollowTimeoutAsFollowTimeout proves the Provider's
// own timeout classification survives the Endpoint switch.
//
// The Provider reports this code when it classified the expiry in its response
// document instead of returning a wrapped context error, so the sentinel checks
// cannot see it. Without the branch the correct classification falls through to
// provider_error, which tells the operator the Provider failed when it only
// reached its bound.
func TestStartFollowReportsProviderFollowTimeoutAsFollowTimeout(t *testing.T) {
	executor := &followExecutor{followErr: &adapter.StreamError{Code: "follow_timeout", Message: "provider budget expired"}}
	service, transport := newFollowService(t, executor)
	service.startFollow(context.Background(), channel.Frame{Type: channel.FrameOutputFollowRequest, RequestID: "req-provider-timeout", OutputFollowRequest: &protocol.OutputFollowRequest{ResourceID: "r"}})
	waitForFrames(t, transport, channel.FrameOutputEnd, 1)
	transport.mu.Lock()
	end := transport.frames[len(transport.frames)-1].OutputEnd
	transport.mu.Unlock()
	if end == nil || end.ErrorCode != "follow_timeout" {
		t.Fatalf("end=%#v want follow_timeout", end)
	}
}
