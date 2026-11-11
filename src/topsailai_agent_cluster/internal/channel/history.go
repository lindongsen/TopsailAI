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

// maxPendingHistory bounds concurrent history queries so one operator cannot
// exhaust the channel with provider reads.
const maxPendingHistory = 64

type pendingHistoryRequest struct {
	peer     *Peer
	response chan protocol.HistoryResult
}

// RequestHistory binds a bounded history query to one authenticated connection
// generation. The query is a live provider read, so it is never served from a
// cache and never retried against a different connection.
func (s *Server) RequestHistory(parent context.Context, endpointID string, query protocol.HistoryQuery) (protocol.HistoryResult, error) {
	ctx, cancel := context.WithTimeout(parent, 10*time.Second)
	defer cancel()
	peer, err := s.currentPeer(endpointID)
	if err != nil {
		return protocol.HistoryResult{}, err
	}
	id := security.NewRequestID()
	response := make(chan protocol.HistoryResult, 1)
	s.Mu.Lock()
	if len(s.pendingHistory) >= maxPendingHistory {
		s.Mu.Unlock()
		return protocol.HistoryResult{}, errors.New("history query capacity exceeded")
	}
	if s.pendingHistory == nil {
		s.pendingHistory = make(map[string]pendingHistoryRequest)
	}
	s.pendingHistory[id] = pendingHistoryRequest{peer: peer, response: response}
	s.Mu.Unlock()
	defer func() { s.Mu.Lock(); delete(s.pendingHistory, id); s.Mu.Unlock() }()
	frame := Frame{Type: FrameHistoryRequest, ProtocolVersion: ProtocolVersion, RequestID: id, ConnectionGeneration: strconv.FormatInt(peer.ConnectionGeneration, 10), HistoryQuery: &query, EndpointToken: security.EndpointToken(parent)}
	if err := wsjson.Write(ctx, peer.Conn, frame); err != nil {
		return protocol.HistoryResult{}, err
	}
	select {
	case result := <-response:
		if err := ctx.Err(); err != nil {
			return protocol.HistoryResult{}, err
		}
		if s.Fence.Check(endpointID, peer.ConnectionGeneration) != nil {
			return protocol.HistoryResult{}, errors.New("history connection changed")
		}
		return result, nil
	case <-ctx.Done():
		return protocol.HistoryResult{}, ctx.Err()
	}
}

// deliverHistory accepts only the exact pending peer, never another endpoint or reconnect.
func (s *Server) deliverHistory(peer *Peer, frame Frame) {
	s.Mu.Lock()
	defer s.Mu.Unlock()
	pending, ok := s.pendingHistory[frame.RequestID]
	if !ok || pending.peer != peer || frame.HistoryResult == nil {
		return
	}
	delete(s.pendingHistory, frame.RequestID)
	pending.response <- *frame.HistoryResult
}

// failPendingHistory releases every waiter for one endpoint. A disconnected
// Endpoint can never answer, so waiting for the deadline would only delay an
// error the caller must see immediately.
func (s *Server) failPendingHistory(endpointID string) {
	s.Mu.Lock()
	defer s.Mu.Unlock()
	for requestID, pending := range s.pendingHistory {
		if pending.peer.EndpointID != endpointID {
			continue
		}
		delete(s.pendingHistory, requestID)
		pending.response <- protocol.HistoryResult{ErrorCode: "endpoint_unavailable"}
	}
}
