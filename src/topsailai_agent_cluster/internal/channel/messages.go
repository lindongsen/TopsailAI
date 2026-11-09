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

// maxPendingMessages bounds concurrent messages queries so one operator cannot
// exhaust the channel with provider reads.
const maxPendingMessages = 64

type pendingMessagesRequest struct {
	peer     *Peer
	response chan protocol.MessagesResult
}

// RequestMessages binds a bounded conversation read to one authenticated
// connection generation. The query is a live provider read, so it is never served
// from a cache and never retried against a different connection.
func (s *Server) RequestMessages(parent context.Context, endpointID string, query protocol.MessagesQuery) (protocol.MessagesResult, error) {
	ctx, cancel := context.WithTimeout(parent, 10*time.Second)
	defer cancel()
	peer, err := s.currentPeer(endpointID)
	if err != nil {
		return protocol.MessagesResult{}, err
	}
	id := security.NewRequestID()
	response := make(chan protocol.MessagesResult, 1)
	s.Mu.Lock()
	if len(s.pendingMessages) >= maxPendingMessages {
		s.Mu.Unlock()
		return protocol.MessagesResult{}, errors.New("messages query capacity exceeded")
	}
	if s.pendingMessages == nil {
		s.pendingMessages = make(map[string]pendingMessagesRequest)
	}
	s.pendingMessages[id] = pendingMessagesRequest{peer: peer, response: response}
	s.Mu.Unlock()
	defer func() { s.Mu.Lock(); delete(s.pendingMessages, id); s.Mu.Unlock() }()
	frame := Frame{Type: FrameMessagesRequest, ProtocolVersion: ProtocolVersion, RequestID: id, ConnectionGeneration: strconv.FormatInt(peer.ConnectionGeneration, 10), MessagesQuery: &query}
	if err := wsjson.Write(ctx, peer.Conn, frame); err != nil {
		return protocol.MessagesResult{}, err
	}
	select {
	case result := <-response:
		if err := ctx.Err(); err != nil {
			return protocol.MessagesResult{}, err
		}
		if s.Fence.Check(endpointID, peer.ConnectionGeneration) != nil {
			return protocol.MessagesResult{}, errors.New("messages connection changed")
		}
		return result, nil
	case <-ctx.Done():
		return protocol.MessagesResult{}, ctx.Err()
	}
}

// deliverMessages accepts only the exact pending peer, never another endpoint or reconnect.
func (s *Server) deliverMessages(peer *Peer, frame Frame) {
	s.Mu.Lock()
	defer s.Mu.Unlock()
	pending, ok := s.pendingMessages[frame.RequestID]
	if !ok || pending.peer != peer || frame.MessagesResult == nil {
		return
	}
	delete(s.pendingMessages, frame.RequestID)
	pending.response <- *frame.MessagesResult
}

// failPendingMessages releases every waiter for one endpoint. A disconnected
// Endpoint can never answer, so waiting for the deadline would only delay an
// error the caller must see immediately.
func (s *Server) failPendingMessages(endpointID string) {
	s.Mu.Lock()
	defer s.Mu.Unlock()
	for requestID, pending := range s.pendingMessages {
		if pending.peer.EndpointID != endpointID {
			continue
		}
		delete(s.pendingMessages, requestID)
		pending.response <- protocol.MessagesResult{ErrorCode: "endpoint_unavailable"}
	}
}
