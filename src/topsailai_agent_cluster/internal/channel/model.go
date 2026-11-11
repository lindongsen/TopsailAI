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

// maxPendingModelCatalog bounds concurrent model-catalog reads so one operator
// cannot exhaust the channel with provider reads.
const maxPendingModelCatalog = 64

type pendingModelCatalogRequest struct {
	peer     *Peer
	response chan protocol.ModelCatalog
}

// RequestModelCatalog binds a bounded model-catalog read to one authenticated
// connection generation. The read is a live provider query, so it is never served
// from a cache and never retried against a different connection.
func (s *Server) RequestModelCatalog(parent context.Context, endpointID string, query protocol.ModelCatalogQuery) (protocol.ModelCatalog, error) {
	ctx, cancel := context.WithTimeout(parent, 10*time.Second)
	defer cancel()
	peer, err := s.currentPeer(endpointID)
	if err != nil {
		return protocol.ModelCatalog{}, err
	}
	id := security.NewRequestID()
	response := make(chan protocol.ModelCatalog, 1)
	s.Mu.Lock()
	if len(s.pendingModelCatalog) >= maxPendingModelCatalog {
		s.Mu.Unlock()
		return protocol.ModelCatalog{}, errors.New("model catalog query capacity exceeded")
	}
	if s.pendingModelCatalog == nil {
		s.pendingModelCatalog = make(map[string]pendingModelCatalogRequest)
	}
	s.pendingModelCatalog[id] = pendingModelCatalogRequest{peer: peer, response: response}
	s.Mu.Unlock()
	defer func() { s.Mu.Lock(); delete(s.pendingModelCatalog, id); s.Mu.Unlock() }()
	frame := Frame{Type: FrameModelCatalogRequest, ProtocolVersion: ProtocolVersion, RequestID: id, ConnectionGeneration: strconv.FormatInt(peer.ConnectionGeneration, 10), ModelCatalogQuery: &query, EndpointToken: security.EndpointToken(parent)}
	if err := wsjson.Write(ctx, peer.Conn, frame); err != nil {
		return protocol.ModelCatalog{}, err
	}
	select {
	case result := <-response:
		if err := ctx.Err(); err != nil {
			return protocol.ModelCatalog{}, err
		}
		if s.Fence.Check(endpointID, peer.ConnectionGeneration) != nil {
			return protocol.ModelCatalog{}, errors.New("model catalog connection changed")
		}
		return result, nil
	case <-ctx.Done():
		return protocol.ModelCatalog{}, ctx.Err()
	}
}

// deliverModelCatalog accepts only the exact pending peer, never another endpoint
// or reconnect.
func (s *Server) deliverModelCatalog(peer *Peer, frame Frame) {
	s.Mu.Lock()
	defer s.Mu.Unlock()
	pending, ok := s.pendingModelCatalog[frame.RequestID]
	if !ok || pending.peer != peer || frame.ModelCatalog == nil {
		return
	}
	delete(s.pendingModelCatalog, frame.RequestID)
	pending.response <- *frame.ModelCatalog
}

// failPendingModelCatalog releases every waiter for one endpoint. A disconnected
// Endpoint can never answer, so waiting for the deadline would only delay an error
// the caller must see immediately.
func (s *Server) failPendingModelCatalog(endpointID string) {
	s.Mu.Lock()
	defer s.Mu.Unlock()
	for requestID, pending := range s.pendingModelCatalog {
		if pending.peer.EndpointID != endpointID {
			continue
		}
		delete(s.pendingModelCatalog, requestID)
		pending.response <- protocol.ModelCatalog{ErrorCode: "endpoint_unavailable"}
	}
}
