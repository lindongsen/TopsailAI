package channel

import (
	"context"
	"errors"
	"strconv"
	"time"

	"github.com/coder/websocket/wsjson"
	"topsailai_agent_cluster/internal/protocol"
	"topsailai_agent_cluster/internal/security"
)

// maxPendingMetricsBatch bounds concurrent batch message-count queries.
//
// The bound is deliberately lower than maxPendingMetrics. One batch request
// already covers a whole Endpoint's visible rows, so a caller needs one request
// per Endpoint rather than one per row. A bound as large as the single-session
// bound would therefore admit far more provider work than the single-session
// path ever could, because each admitted request now carries a set.
const maxPendingMetricsBatch = 16

type pendingMetricsBatchRequest struct {
	peer     *Peer
	response chan protocol.SessionMetricsBatch
}

// RequestMetricsBatch binds one bounded set read to one authenticated connection
// generation. The counts are a live provider observation, so they are never
// served from a cache and never retried against a different connection.
func (s *Server) RequestMetricsBatch(parent context.Context, endpointID string, query protocol.SessionMetricsBatchQuery) (protocol.SessionMetricsBatch, error) {
	ctx, cancel := context.WithTimeout(parent, 9*time.Second)
	defer cancel()
	peer, err := s.currentPeer(endpointID)
	if err != nil {
		return protocol.SessionMetricsBatch{}, err
	}
	id := security.NewRequestID()
	response := make(chan protocol.SessionMetricsBatch, 1)
	s.Mu.Lock()
	if len(s.pendingMetricsBatch) >= maxPendingMetricsBatch {
		s.Mu.Unlock()
		return protocol.SessionMetricsBatch{}, errors.New("metrics batch query capacity exceeded")
	}
	if s.pendingMetricsBatch == nil {
		s.pendingMetricsBatch = make(map[string]pendingMetricsBatchRequest)
	}
	s.pendingMetricsBatch[id] = pendingMetricsBatchRequest{peer: peer, response: response}
	s.Mu.Unlock()
	defer func() { s.Mu.Lock(); delete(s.pendingMetricsBatch, id); s.Mu.Unlock() }()
	frame := Frame{Type: FrameMetricsBatchRequest, ProtocolVersion: ProtocolVersion, RequestID: id, ConnectionGeneration: strconv.FormatInt(peer.ConnectionGeneration, 10), MetricsBatchQuery: &query, EndpointToken: security.EndpointToken(parent)}
	if err := wsjson.Write(ctx, peer.Conn, frame); err != nil {
		return protocol.SessionMetricsBatch{}, err
	}
	select {
	case result := <-response:
		if err := ctx.Err(); err != nil {
			return protocol.SessionMetricsBatch{}, err
		}
		if s.Fence.Check(endpointID, peer.ConnectionGeneration) != nil {
			return protocol.SessionMetricsBatch{}, errors.New("metrics batch connection changed")
		}
		return result, nil
	case <-ctx.Done():
		return protocol.SessionMetricsBatch{}, ctx.Err()
	}
}

// deliverMetricsBatch accepts only the exact pending peer, never another endpoint
// or a reconnect.
func (s *Server) deliverMetricsBatch(peer *Peer, frame Frame) {
	s.Mu.Lock()
	defer s.Mu.Unlock()
	pending, ok := s.pendingMetricsBatch[frame.RequestID]
	if !ok || pending.peer != peer || frame.MetricsBatchResult == nil {
		return
	}
	delete(s.pendingMetricsBatch, frame.RequestID)
	pending.response <- *frame.MetricsBatchResult
}

// failPendingMetricsBatch releases every waiter for one endpoint. A disconnected
// Endpoint can never answer, so waiting for the deadline would only delay an
// error the caller must see immediately.
func (s *Server) failPendingMetricsBatch(endpointID string) {
	s.Mu.Lock()
	defer s.Mu.Unlock()
	for requestID, pending := range s.pendingMetricsBatch {
		if pending.peer.EndpointID != endpointID {
			continue
		}
		delete(s.pendingMetricsBatch, requestID)
		pending.response <- protocol.SessionMetricsBatch{ErrorCode: "endpoint_unavailable"}
	}
}
