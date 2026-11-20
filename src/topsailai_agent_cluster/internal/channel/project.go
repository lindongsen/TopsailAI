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

// maxPendingProjectCatalog bounds concurrent project-catalog reads so one operator
// cannot exhaust the channel with provider reads.
const maxPendingProjectCatalog = 64

type pendingProjectCatalogRequest struct {
	peer     *Peer
	response chan protocol.ProjectCatalog
}

// RequestProjectCatalog binds a bounded project-catalog read to one authenticated
// connection generation. The read is a live provider query, so it is never served
// from a cache and never retried against a different connection.
func (s *Server) RequestProjectCatalog(parent context.Context, endpointID string, query protocol.ProjectCatalogQuery) (protocol.ProjectCatalog, error) {
	ctx, cancel := context.WithTimeout(parent, 10*time.Second)
	defer cancel()
	peer, err := s.currentPeer(endpointID)
	if err != nil {
		return protocol.ProjectCatalog{}, err
	}
	id := security.NewRequestID()
	response := make(chan protocol.ProjectCatalog, 1)
	s.Mu.Lock()
	if len(s.pendingProjectCatalog) >= maxPendingProjectCatalog {
		s.Mu.Unlock()
		return protocol.ProjectCatalog{}, errors.New("project catalog query capacity exceeded")
	}
	if s.pendingProjectCatalog == nil {
		s.pendingProjectCatalog = make(map[string]pendingProjectCatalogRequest)
	}
	s.pendingProjectCatalog[id] = pendingProjectCatalogRequest{peer: peer, response: response}
	s.Mu.Unlock()
	defer func() { s.Mu.Lock(); delete(s.pendingProjectCatalog, id); s.Mu.Unlock() }()
	frame := Frame{Type: FrameProjectCatalogRequest, ProtocolVersion: ProtocolVersion, RequestID: id, ConnectionGeneration: strconv.FormatInt(peer.ConnectionGeneration, 10), ProjectCatalogQuery: &query, EndpointCredential: security.EndpointCredentialFor(parent), EndpointRequestDigest: security.EndpointRequestDigestFrom(parent)}
	if err := wsjson.Write(ctx, peer.Conn, frame); err != nil {
		return protocol.ProjectCatalog{}, err
	}
	select {
	case result := <-response:
		if err := ctx.Err(); err != nil {
			return protocol.ProjectCatalog{}, err
		}
		if s.Fence.Check(endpointID, peer.ConnectionGeneration) != nil {
			return protocol.ProjectCatalog{}, errors.New("project catalog connection changed")
		}
		return result, nil
	case <-ctx.Done():
		return protocol.ProjectCatalog{}, ctx.Err()
	}
}

// deliverProjectCatalog accepts only the exact pending peer, never another endpoint
// or reconnect.
func (s *Server) deliverProjectCatalog(peer *Peer, frame Frame) {
	s.Mu.Lock()
	defer s.Mu.Unlock()
	pending, ok := s.pendingProjectCatalog[frame.RequestID]
	if !ok || pending.peer != peer || frame.ProjectCatalog == nil {
		return
	}
	delete(s.pendingProjectCatalog, frame.RequestID)
	pending.response <- *frame.ProjectCatalog
}

// failPendingProjectCatalog releases every waiter for one endpoint. A disconnected
// Endpoint can never answer, so waiting for the deadline would only delay an error
// the caller must see immediately.
func (s *Server) failPendingProjectCatalog(endpointID string) {
	s.Mu.Lock()
	defer s.Mu.Unlock()
	for requestID, pending := range s.pendingProjectCatalog {
		if pending.peer.EndpointID != endpointID {
			continue
		}
		delete(s.pendingProjectCatalog, requestID)
		pending.response <- protocol.ProjectCatalog{ErrorCode: "endpoint_unavailable"}
	}
}
