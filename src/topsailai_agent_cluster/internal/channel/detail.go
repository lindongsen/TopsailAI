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

// maxPendingDetail bounds concurrent session-record queries so one operator
// cannot exhaust the channel with provider reads.
//
// The bound matches the messages bound because a record read reaches the same
// provider surface. A larger bound would let record reads crowd out the reads
// they are meant to explain.
const maxPendingDetail = 64

type pendingDetailRequest struct {
	peer     *Peer
	response chan protocol.SessionDetail
}

// RequestDetail binds a bounded session-record read to one authenticated
// connection generation. The record is provider state, so it is never served from
// a cache and never retried against a different connection.
func (s *Server) RequestDetail(parent context.Context, endpointID string, query protocol.SessionDetailQuery) (protocol.SessionDetail, error) {
	ctx, cancel := context.WithTimeout(parent, 10*time.Second)
	defer cancel()
	peer, err := s.currentPeer(endpointID)
	if err != nil {
		return protocol.SessionDetail{}, err
	}
	id := security.NewRequestID()
	response := make(chan protocol.SessionDetail, 1)
	s.Mu.Lock()
	if len(s.pendingDetail) >= maxPendingDetail {
		s.Mu.Unlock()
		return protocol.SessionDetail{}, errors.New("detail query capacity exceeded")
	}
	if s.pendingDetail == nil {
		s.pendingDetail = make(map[string]pendingDetailRequest)
	}
	s.pendingDetail[id] = pendingDetailRequest{peer: peer, response: response}
	s.Mu.Unlock()
	defer func() { s.Mu.Lock(); delete(s.pendingDetail, id); s.Mu.Unlock() }()
	frame := Frame{Type: FrameDetailRequest, ProtocolVersion: ProtocolVersion, RequestID: id, ConnectionGeneration: strconv.FormatInt(peer.ConnectionGeneration, 10), DetailQuery: &query, EndpointCredential: security.EndpointCredentialFor(parent), EndpointRequestDigest: security.EndpointRequestDigestFrom(parent)}
	if err := wsjson.Write(ctx, peer.Conn, frame); err != nil {
		return protocol.SessionDetail{}, err
	}
	select {
	case result := <-response:
		if err := ctx.Err(); err != nil {
			return protocol.SessionDetail{}, err
		}
		if s.Fence.Check(endpointID, peer.ConnectionGeneration) != nil {
			return protocol.SessionDetail{}, errors.New("detail connection changed")
		}
		return result, nil
	case <-ctx.Done():
		return protocol.SessionDetail{}, ctx.Err()
	}
}

// deliverDetail accepts only the exact pending peer, never another endpoint or reconnect.
func (s *Server) deliverDetail(peer *Peer, frame Frame) {
	s.Mu.Lock()
	defer s.Mu.Unlock()
	pending, ok := s.pendingDetail[frame.RequestID]
	if !ok || pending.peer != peer || frame.DetailResult == nil {
		return
	}
	delete(s.pendingDetail, frame.RequestID)
	pending.response <- *frame.DetailResult
}

// failPendingDetail releases every waiter for one endpoint. A disconnected
// Endpoint can never answer, so waiting for the deadline would only delay an
// error the caller must see immediately.
func (s *Server) failPendingDetail(endpointID string) {
	s.Mu.Lock()
	defer s.Mu.Unlock()
	for requestID, pending := range s.pendingDetail {
		if pending.peer.EndpointID != endpointID {
			continue
		}
		delete(s.pendingDetail, requestID)
		pending.response <- protocol.SessionDetail{ErrorCode: "endpoint_unavailable"}
	}
}
