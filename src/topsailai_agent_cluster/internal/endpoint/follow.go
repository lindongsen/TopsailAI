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
	switch {
	case err == nil:
	case errors.Is(err, context.Canceled), errors.Is(err, context.DeadlineExceeded):
		code = "cancelled"
	case errors.Is(err, adapter.ErrUnsupported):
		// The adapter cannot stream. Reporting unsupported is honest; degrading
		// the request into a snapshot would show a stream that never updates.
		code = "unsupported"
	default:
		code = "provider_error"
		s.logError("follow provider output", err)
	}
	s.sendFollowEnd(ctx, requestID, code, truncated)
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
