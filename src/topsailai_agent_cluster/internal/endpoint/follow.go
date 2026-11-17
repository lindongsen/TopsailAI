package endpoint

import (
	"context"
	"errors"
	"log/slog"
	"time"

	"topsailai_agent_cluster/internal/adapter"
	"topsailai_agent_cluster/internal/channel"
	"topsailai_agent_cluster/internal/protocol"
)

// startFollow admits one streaming output follow and runs it outside the channel
// read loop. The read loop must never block on a follow: a follow stays open for
// as long as the operator watches, so running it inline would stop command,
// heartbeat, inventory and launch delivery for the whole session.
//
// Admission is bounded and non-blocking. A follow beyond the concurrency bound is
// rejected instead of queued, because a queued follow would start late while the
// operator already believes the stream is live.
func (s *Service) startFollow(ctx context.Context, frame channel.Frame) {
	requestID := frame.RequestID
	if frame.OutputFollowRequest == nil {
		s.sendFollowEnd(ctx, requestID, "invalid_request", false)
		return
	}
	// The policy check runs before the follower is consulted, so a refused caller
	// cannot infer whether this Endpoint can stream. A refusal ends the stream
	// with a terminal frame rather than a snapshot, because the consumer is
	// waiting for a stream and a snapshot would look like a complete one.
	if err := s.permitOperation(frame, protocol.OperationOutputFollow); err != nil {
		s.sendFollowEnd(ctx, requestID, s.refuseFrame(ctx, frame, protocol.OperationOutputFollow, err), false)
		return
	}
	follower, ok := s.executor.(OutputFollower)
	if !ok {
		// The adapter cannot stream. Reporting unsupported is honest; degrading
		// the request into a snapshot would show a stream that never updates.
		s.sendFollowEnd(ctx, requestID, "unsupported", false)
		return
	}
	select {
	case s.followSlots <- struct{}{}:
	default:
		s.sendFollowEnd(ctx, requestID, "too_many_follows", false)
		return
	}
	followCtx, cancel := context.WithCancel(ctx)
	s.followMu.Lock()
	if _, exists := s.activeFollows[requestID]; exists {
		s.followMu.Unlock()
		cancel()
		<-s.followSlots
		s.sendFollowEnd(ctx, requestID, "duplicate_request", false)
		return
	}
	s.activeFollows[requestID] = cancel
	s.followMu.Unlock()

	s.wg.Add(1)
	go func() {
		defer s.wg.Done()
		defer func() {
			s.followMu.Lock()
			delete(s.activeFollows, requestID)
			s.followMu.Unlock()
			cancel()
			<-s.followSlots
		}()
		s.runFollow(followCtx, requestID, follower, *frame.OutputFollowRequest)
	}()
}

// runFollow streams chunks until the adapter stops, then always terminates the
// stream with exactly one end frame. A consumer that stops receiving chunks
// without an end frame must treat the stream as interrupted, so the end frame is
// sent on every exit path, including cancellation and adapter failure.
func (s *Service) runFollow(ctx context.Context, requestID string, follower OutputFollower, request protocol.OutputFollowRequest) {
	truncated := false
	err := follower.FollowOutput(ctx, request, func(chunk protocol.OutputChunk) error {
		if chunk.Truncated {
			truncated = true
		}
		if chunk.ObservedAtMS == 0 {
			chunk.ObservedAtMS = time.Now().UnixMilli()
		}
		return s.channel.SendFrame(ctx, channel.Frame{
			Type:            channel.FrameOutputChunk,
			ProtocolVersion: channel.ProtocolVersion,
			RequestID:       requestID,
			OutputChunk:     &chunk,
		})
	})
	code := ""
	// A Provider-reported code is the classification when this Endpoint
	// recognises it. It is extracted once so the switch does not have to call the
	// extractor twice, and so an unrecognised code falls through to the sentinel
	// checks below instead of being forwarded as if it were a Cluster code.
	providerCode, providerCoded := providerStreamCode(err)
	switch {
	case err == nil:
	case errors.Is(err, context.Canceled), errors.Is(err, context.DeadlineExceeded):
		code = "cancelled"
	case providerCoded && providerCode == "cancelled":
		// The Provider reported its own cancellation, so the stream ended for a
		// reason the Provider already classified. Reporting it as provider_error
		// told the operator the Provider had failed when it had behaved correctly,
		// and it hid the one fact that explains the empty tail: the stream was
		// stopped rather than broken. This case must precede the default, because
		// the default is what misreported it.
		code = "cancelled"
		s.logFollowFailure(requestID, request, code, err)
	case providerCoded && providerCode == "unsupported":
		// The Provider cannot tail this target. That is a capability answer, not a
		// fault, so it keeps the same code the adapter-level sentinel produces.
		code = "unsupported"
		s.logFollowFailure(requestID, request, code, err)
	case providerCoded && providerCode == "invalid_request":
		// The Provider rejected the request it was given, so the fault is in the
		// request rather than in the Provider. Naming it provider_error sent the
		// operator to investigate a Provider that refused correctly.
		code = "invalid_request"
		s.logFollowFailure(requestID, request, code, err)
	case errors.Is(err, adapter.ErrUnsupported):
		// The adapter cannot stream. Reporting unsupported is honest; degrading
		// the request into a snapshot would show a stream that never updates.
		code = "unsupported"
	case errors.Is(err, adapter.ErrBusy):
		// A capacity refusal means the adapter was never invoked, so it proves
		// nothing about the provider. Reporting it as provider_error sent the
		// operator to investigate a provider that was never called, and the same
		// follow may succeed unchanged once the competing invocation finishes.
		// This case must precede the default, because the default is what
		// misreported it.
		code = protocol.AdapterBusy
		s.logFollowFailure(requestID, request, code, err)
	case errors.Is(err, adapter.ErrOutputLimit):
		// A local byte budget stopped the stream, so the provider was not at
		// fault. Reporting it as provider_error sent the operator to investigate a
		// provider that behaved correctly, and the same follow may succeed with a
		// smaller request. This case must precede the default, because the default
		// is what misreported it.
		code = protocol.OutputLimit
		s.logFollowFailure(requestID, request, code, err)
	default:
		code = "provider_error"
		s.logFollowFailure(requestID, request, code, err)
	}
	s.sendFollowEnd(ctx, requestID, code, truncated)
}

// providerStreamCode extracts the Provider's own error code from a stream failure.
//
// The code is the only field that carries the Provider's classification, so it is
// read here rather than parsed out of the message. Parsing prose would make the
// classification depend on wording, and the wording is the part a Provider is free
// to change.
//
// The second return value reports whether a code was found at all, because an
// empty code and an absent code are different facts: a Provider that reported no
// code has not classified the failure, so the caller must fall back to its own
// sentinel checks instead of treating the absence as a classification.
func providerStreamCode(err error) (string, bool) {
	var streamErr *adapter.StreamError
	if !errors.As(err, &streamErr) {
		return "", false
	}
	if streamErr.Code == "" {
		return "", false
	}
	return streamErr.Code, true
}

// sendFollowEnd emits the single terminal frame for a follow request.
//
// Delivery is best-effort. The Endpoint keeps no follow journal, so a terminal
// frame that cannot be sent is never queued and never replayed on reconnect.
// That is deliberate: retaining it would add a durable record type, a reconnect
// flush order and a retention bound to the command deduplication journal, which
// is a larger change than the contract requires.
//
// The contract that makes best-effort safe is on the Server: a disconnected
// Endpoint always terminates its pending follows with the Server-inferred
// endpoint_offline code, so the consumer still learns the stream was interrupted
// rather than finished. The Endpoint's own terminal code is therefore advisory,
// and a consumer must never treat a missing terminal frame as a clean end.
//
// A lost terminal frame is a contract event, not routine noise, so it is
// recorded with the request ID and the code that was never delivered. Logging it
// as a deferred retry would be false, because no retry exists.
func (s *Service) sendFollowEnd(ctx context.Context, requestID, code string, truncated bool) {
	end := protocol.OutputEnd{ErrorCode: code, ObservedAtMS: time.Now().UnixMilli(), Truncated: truncated}
	if err := s.channel.SendFrame(ctx, channel.Frame{
		Type:            channel.FrameOutputEnd,
		ProtocolVersion: channel.ProtocolVersion,
		RequestID:       requestID,
		OutputEnd:       &end,
	}); err != nil {
		s.logFollowEndLost(requestID, code, err)
	}
}

// logFollowEndLost records that a follow terminal frame never reached the Server.
//
// An offline channel stays at WARN because it is a connectivity state rather
// than an operation failure, but the message states the loss explicitly instead
// of claiming the frame was deferred. Any other transport failure is a genuine
// error and stays at ERROR.
func (s *Service) logFollowEndLost(requestID, code string, err error) {
	if s.logger == nil {
		return
	}
	level := slog.LevelWarn
	if !errors.Is(err, channel.ErrOffline) {
		level = slog.LevelError
	}
	s.logger.Log(context.Background(), level, "output follow terminal frame lost",
		"request_id", requestID, "error_code", code, "error", err)
}

// logFollowFailure records why one follow stream ended abnormally, with the
// fields needed to identify the affected session without re-running the code.
//
// The generic logError helper records only the error value, which made a
// provider_error impossible to attribute: the operator could see that some
// follow failed but not which Endpoint, request, resource or provider
// generation it belonged to, so the only way to investigate was to reproduce
// the failure and watch it happen. The request carries every one of those
// identities, so they are recorded here instead of being discarded.
//
// The reported code is logged alongside the error because the code is the
// classification the operator sees, and the error is the evidence behind it.
// Logging only one of the two hides either the symptom or its cause.
func (s *Service) logFollowFailure(requestID string, request protocol.OutputFollowRequest, code string, err error) {
	if s.logger == nil {
		return
	}
	s.logger.Error("output follow failed",
		"request_id", requestID,
		"endpoint_id", request.EndpointID,
		"resource_id", request.ResourceID,
		"provider_generation", request.ProviderGeneration,
		"max_bytes", request.MaxBytes,
		"max_lines", request.MaxLines,
		"error_code", code,
		"error", err)
}

// stopFollows cancels every active follow. It runs during shutdown so a provider
// child process is not left streaming after the Endpoint stops serving.
func (s *Service) stopFollows() {
	s.followMu.Lock()
	cancels := make([]context.CancelFunc, 0, len(s.activeFollows))
	for _, cancel := range s.activeFollows {
		cancels = append(cancels, cancel)
	}
	s.followMu.Unlock()
	for _, cancel := range cancels {
		cancel()
	}
}

// cancelFollow stops one follow because its consumer stopped watching.
//
// The Server drops its pending entry the moment the operator stops reading, so
// the chunks this Endpoint keeps producing are discarded on arrival. Without this
// cancellation the Endpoint would keep the follow goroutine, one of its
// maxConcurrentFollows slots and the adapter's follow slot until the adapter
// deadline expired, which is two minutes in the deployed configuration. Two
// abandoned follows were therefore enough to make the next follow wait for
// capacity it could not see.
//
// Only the cancel function is invoked here. Deleting the entry and releasing the
// slot stay in the goroutine's deferred cleanup, so a cancel that races the
// adapter's own exit cannot release the slot twice.
//
// An unknown request ID is not an error: the follow may have already sent its
// terminal frame, and the Server sends this frame only when it believes the
// Endpoint is still streaming. Treating that race as a failure would log an error
// for a correct sequence.
func (s *Service) cancelFollow(requestID string) {
	s.followMu.Lock()
	cancel, ok := s.activeFollows[requestID]
	s.followMu.Unlock()
	if !ok {
		return
	}
	cancel()
}
