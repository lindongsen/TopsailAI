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

// maxPendingMetrics bounds concurrent message-count queries so one operator
// cannot exhaust the channel with provider reads.
//
// The bound matches the messages bound because a count read reaches the same
// provider control channel. A larger bound would let count reads crowd out the
// conversation reads they are meant to summarise.
const maxPendingMetrics = 64

type pendingMetricsRequest struct {
	peer     *Peer
	response chan protocol.SessionMetrics
}

// RequestMetrics binds a bounded message-count read to one authenticated
// connection generation. The counts are a live provider observation, so they are
// never served from a cache and never retried against a different connection.
func (s *Server) RequestMetrics(parent context.Context, endpointID string, query protocol.SessionMetricsQuery) (protocol.SessionMetrics, error) {
	ctx, cancel := context.WithTimeout(parent, 10*time.Second)
	defer cancel()
	peer, err := s.currentPeer(endpointID)
	if err != nil {
		return protocol.SessionMetrics{}, err
	}
	id := security.NewRequestID()
	response := make(chan protocol.SessionMetrics, 1)
	s.Mu.Lock()
	if len(s.pendingMetrics) >= maxPendingMetrics {
		s.Mu.Unlock()
		return protocol.SessionMetrics{}, errors.New("metrics query capacity exceeded")
	}
	if s.pendingMetrics == nil {
		s.pendingMetrics = make(map[string]pendingMetricsRequest)
	}
	s.pendingMetrics[id] = pendingMetricsRequest{peer: peer, response: response}
	s.Mu.Unlock()
	defer func() { s.Mu.Lock(); delete(s.pendingMetrics, id); s.Mu.Unlock() }()
	frame := Frame{Type: FrameMetricsRequest, ProtocolVersion: ProtocolVersion, RequestID: id, ConnectionGeneration: strconv.FormatInt(peer.ConnectionGeneration, 10), MetricsQuery: &query, EndpointToken: security.EndpointToken(parent)}
	if err := wsjson.Write(ctx, peer.Conn, frame); err != nil {
		return protocol.SessionMetrics{}, err
	}
	select {
	case result := <-response:
		if err := ctx.Err(); err != nil {
			return protocol.SessionMetrics{}, err
		}
		if s.Fence.Check(endpointID, peer.ConnectionGeneration) != nil {
			return protocol.SessionMetrics{}, errors.New("metrics connection changed")
		}
		return result, nil
	case <-ctx.Done():
		return protocol.SessionMetrics{}, ctx.Err()
	}
}

// deliverMetrics accepts only the exact pending peer, never another endpoint or reconnect.
func (s *Server) deliverMetrics(peer *Peer, frame Frame) {
	s.Mu.Lock()
	defer s.Mu.Unlock()
	pending, ok := s.pendingMetrics[frame.RequestID]
	if !ok || pending.peer != peer || frame.MetricsResult == nil {
		return
	}
	delete(s.pendingMetrics, frame.RequestID)
	pending.response <- *frame.MetricsResult
}

// failPendingMetrics releases every waiter for one endpoint. A disconnected
// Endpoint can never answer, so waiting for the deadline would only delay an
// error the caller must see immediately.
func (s *Server) failPendingMetrics(endpointID string) {
	s.Mu.Lock()
	defer s.Mu.Unlock()
	for requestID, pending := range s.pendingMetrics {
		if pending.peer.EndpointID != endpointID {
			continue
		}
		delete(s.pendingMetrics, requestID)
		pending.response <- protocol.SessionMetrics{ErrorCode: "endpoint_unavailable"}
	}
}
