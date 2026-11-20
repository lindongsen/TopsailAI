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

// maxPendingModelRegistry bounds concurrent model-registry reads so one operator
// cannot exhaust the channel with provider reads.
const maxPendingModelRegistry = 64

type pendingModelRegistryRequest struct {
	peer     *Peer
	response chan protocol.ModelRegistry
}

// RequestModelRegistry binds a bounded model-registry read to one authenticated
// connection generation. The read is a live provider query, so it is never served
// from a cache and never retried against a different connection.
func (s *Server) RequestModelRegistry(parent context.Context, endpointID string, query protocol.ModelRegistryQuery) (protocol.ModelRegistry, error) {
	ctx, cancel := context.WithTimeout(parent, 10*time.Second)
	defer cancel()
	peer, err := s.currentPeer(endpointID)
	if err != nil {
		return protocol.ModelRegistry{}, err
	}
	id := security.NewRequestID()
	response := make(chan protocol.ModelRegistry, 1)
	s.Mu.Lock()
	if len(s.pendingModelRegistry) >= maxPendingModelRegistry {
		s.Mu.Unlock()
		return protocol.ModelRegistry{}, errors.New("model registry query capacity exceeded")
	}
	if s.pendingModelRegistry == nil {
		s.pendingModelRegistry = make(map[string]pendingModelRegistryRequest)
	}
	s.pendingModelRegistry[id] = pendingModelRegistryRequest{peer: peer, response: response}
	s.Mu.Unlock()
	defer func() { s.Mu.Lock(); delete(s.pendingModelRegistry, id); s.Mu.Unlock() }()
	frame := Frame{Type: FrameModelRegistryRequest, ProtocolVersion: ProtocolVersion, RequestID: id, ConnectionGeneration: strconv.FormatInt(peer.ConnectionGeneration, 10), ModelRegistryQuery: &query, EndpointCredential: security.EndpointCredentialFor(parent), EndpointRequestDigest: security.EndpointRequestDigestFrom(parent)}
	if err := wsjson.Write(ctx, peer.Conn, frame); err != nil {
		return protocol.ModelRegistry{}, err
	}
	select {
	case result := <-response:
		if err := ctx.Err(); err != nil {
			return protocol.ModelRegistry{}, err
		}
		if s.Fence.Check(endpointID, peer.ConnectionGeneration) != nil {
			return protocol.ModelRegistry{}, errors.New("model registry connection changed")
		}
		return result, nil
	case <-ctx.Done():
		return protocol.ModelRegistry{}, ctx.Err()
	}
}

// deliverModelRegistry accepts only the exact pending peer, never another endpoint
// or reconnect.
func (s *Server) deliverModelRegistry(peer *Peer, frame Frame) {
	s.Mu.Lock()
	defer s.Mu.Unlock()
	pending, ok := s.pendingModelRegistry[frame.RequestID]
	if !ok || pending.peer != peer || frame.ModelRegistry == nil {
		return
	}
	delete(s.pendingModelRegistry, frame.RequestID)
	pending.response <- *frame.ModelRegistry
}

// failPendingModelRegistry releases every waiter for one endpoint. A disconnected
// Endpoint can never answer, so waiting for the deadline would only delay an error
// the caller must see immediately.
func (s *Server) failPendingModelRegistry(endpointID string) {
	s.Mu.Lock()
	defer s.Mu.Unlock()
	for requestID, pending := range s.pendingModelRegistry {
		if pending.peer.EndpointID != endpointID {
			continue
		}
		delete(s.pendingModelRegistry, requestID)
		pending.response <- protocol.ModelRegistry{ErrorCode: "endpoint_unavailable"}
	}
}
