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

type pendingLaunchRequest struct {
	peer     *Peer
	response chan protocol.LaunchOptions
}

// RequestLaunchOptions binds a bounded query to one authenticated connection generation.
func (s *Server) RequestLaunchOptions(parent context.Context, endpointID string, query protocol.LaunchQuery) (protocol.LaunchOptions, error) {
	ctx, cancel := context.WithTimeout(parent, 10*time.Second)
	defer cancel()
	peer, err := s.currentPeer(endpointID)
	if err != nil {
		return protocol.LaunchOptions{}, err
	}
	id := security.NewRequestID()
	response := make(chan protocol.LaunchOptions, 1)
	s.Mu.Lock()
	if len(s.pendingLaunch) >= 64 {
		s.Mu.Unlock()
		return protocol.LaunchOptions{}, errors.New("launch query capacity exceeded")
	}
	if s.pendingLaunch == nil {
		s.pendingLaunch = make(map[string]pendingLaunchRequest)
	}
	s.pendingLaunch[id] = pendingLaunchRequest{peer: peer, response: response}
	s.Mu.Unlock()
	defer func() { s.Mu.Lock(); delete(s.pendingLaunch, id); s.Mu.Unlock() }()
	frame := Frame{Type: FrameLaunchRequest, ProtocolVersion: ProtocolVersion, RequestID: id, ConnectionGeneration: strconv.FormatInt(peer.ConnectionGeneration, 10), LaunchQuery: &query, EndpointToken: security.EndpointToken(parent)}
	if err := wsjson.Write(ctx, peer.Conn, frame); err != nil {
		return protocol.LaunchOptions{}, err
	}
	select {
	case result := <-response:
		if err := ctx.Err(); err != nil {
			return protocol.LaunchOptions{}, err
		}
		if s.Fence.Check(endpointID, peer.ConnectionGeneration) != nil {
			return protocol.LaunchOptions{}, errors.New("launch connection changed")
		}
		return result, nil
	case <-ctx.Done():
		return protocol.LaunchOptions{}, ctx.Err()
	}
}

// deliverLaunch accepts only the exact pending peer, never another endpoint or reconnect.
func (s *Server) deliverLaunch(peer *Peer, frame Frame) {
	s.Mu.Lock()
	defer s.Mu.Unlock()
	pending, ok := s.pendingLaunch[frame.RequestID]
	if !ok || pending.peer != peer || frame.LaunchOptions == nil {
		return
	}
	delete(s.pendingLaunch, frame.RequestID)
	pending.response <- *frame.LaunchOptions
}
