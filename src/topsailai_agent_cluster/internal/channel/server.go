package channel

import (
	"context"
	"crypto/tls"
	"crypto/x509"
	"errors"
	"fmt"
	"net/http"
	"strconv"
	"sync"
	"time"

	"github.com/coder/websocket"
	"github.com/coder/websocket/wsjson"
	"topsailai_agent_cluster/internal/protocol"
	"topsailai_agent_cluster/internal/security"
)

// Server owns Endpoint-initiated WebSocket connections.
type Server struct {
	TLSConfig        *tls.Config
	Fence            *Fence
	Mu               sync.RWMutex
	Active           map[string]*Peer
	HeartbeatTimeout time.Duration
	OnFrame          func(Peer, Frame)
	OnReceipt        func(Peer, protocol.ExecutionReceipt)
	OnReject         func(error)
	OnRejectReason   func(endpointID, certificateIdentity, reason, requestID string)
	RevokedSerials   map[string]bool
	pendingOutput    map[string]pendingOutputRequest
	pendingLaunch    map[string]pendingLaunchRequest
}

// pendingOutputRequest tracks one output request so read-limit failures can be reported.
type pendingOutputRequest struct {
	endpointID string
	response   chan Frame
}

// Peer is one currently connected Endpoint.
const channelReadLimit int64 = 2 << 20

// Peer is one currently connected Endpoint.
type Peer struct {
	EndpointID           string
	InstanceID           string
	Hostname             string
	ConnectionGeneration int64
	Conn                 *websocket.Conn
	LastSeen             time.Time
}

// NewServer constructs a channel server.
func NewServer(tlsConfig *tls.Config) *Server {
	return &Server{TLSConfig: tlsConfig, Fence: NewFence(), Active: make(map[string]*Peer), HeartbeatTimeout: 30 * time.Second, RevokedSerials: make(map[string]bool), pendingOutput: make(map[string]pendingOutputRequest)}
}

// Handler accepts Endpoint-initiated WebSocket upgrades and fences older peers.
func (s *Server) Handler(w http.ResponseWriter, r *http.Request) {
	var certificate *x509.Certificate
	var err error
	if s.TLSConfig != nil {
		certificate, err = peerCertificate(r)
		if err != nil {
			s.reject(err)
			http.Error(w, "mTLS client certificate required", http.StatusUnauthorized)
			return
		}
		if security.IsCertificateRevoked(certificate, s.RevokedSerials) {
			s.reject(errCertificateRevoked(certificate))
			http.Error(w, "client certificate revoked", http.StatusForbidden)
			return
		}
	}
	conn, err := websocket.Accept(w, r, &websocket.AcceptOptions{InsecureSkipVerify: true})
	if err != nil {
		s.reject(err)
		return
	}
	conn.SetReadLimit(channelReadLimit)
	var hello Frame
	if err := wsjson.Read(r.Context(), conn, &hello); err != nil || hello.Type != FrameHello || hello.ProtocolVersion != ProtocolVersion || hello.EndpointID == "" {
		s.sendHelloRejection(r.Context(), conn, hello, "invalid_hello", "invalid hello", certificate)
		return
	}
	if certificate != nil {
		if err := security.ValidateEndpointIdentity(certificate, hello.EndpointID); err != nil {
			s.sendHelloRejection(r.Context(), conn, hello, "identity_mismatch", err.Error(), certificate)
			s.reject(err)
			return
		}
	}
	generation := s.Fence.Acquire(hello.EndpointID)
	peer := &Peer{EndpointID: hello.EndpointID, InstanceID: hello.InstanceID, Hostname: hello.Hostname, ConnectionGeneration: generation, Conn: conn, LastSeen: time.Now()}
	s.Mu.Lock()
	if old := s.Active[hello.EndpointID]; old != nil {
		_ = old.Conn.CloseNow()
	}
	s.Active[hello.EndpointID] = peer
	s.Mu.Unlock()
	ack := Frame{Type: FrameHelloAck, ProtocolVersion: ProtocolVersion, ConnectionGeneration: strconv.FormatInt(generation, 10), EndpointID: hello.EndpointID}
	if err := wsjson.Write(context.Background(), conn, ack); err != nil {
		s.remove(peer)
		return
	}
	go s.readLoop(context.Background(), peer)
}

func (s *Server) sendHelloRejection(ctx context.Context, conn *websocket.Conn, hello Frame, reason, message string, certificate *x509.Certificate) {
	frame := Frame{Type: FrameHelloRejected, ProtocolVersion: ProtocolVersion, RequestID: hello.RequestID, EndpointID: hello.EndpointID, Reason: reason}
	_ = wsjson.Write(ctx, conn, frame)
	identity := ""
	if certificate != nil {
		identity = certificate.Subject.CommonName
	}
	if s.OnRejectReason != nil {
		s.OnRejectReason(hello.EndpointID, identity, reason, hello.RequestID)
	}
	_ = conn.Close(websocket.StatusPolicyViolation, message)
}

func errCertificateRevoked(certificate *x509.Certificate) error {
	return fmt.Errorf("peer certificate %s is revoked", certificate.SerialNumber.String())
}

func peerCertificate(r *http.Request) (*x509.Certificate, error) {
	if r.TLS == nil || len(r.TLS.PeerCertificates) == 0 {
		return nil, fmt.Errorf("mTLS peer certificate is missing")
	}
	return r.TLS.PeerCertificates[0], nil
}

func (s *Server) reject(err error) {
	if s.OnReject != nil {
		s.OnReject(err)
	}
}

func (s *Server) readLoop(ctx context.Context, peer *Peer) {
	defer s.remove(peer)
	for {
		var frame Frame
		if err := wsjson.Read(ctx, peer.Conn, &frame); err != nil {
			if errors.Is(err, websocket.ErrMessageTooBig) {
				s.failPendingOutput(peer.EndpointID, protocol.OutputSnapshotResponse{ErrorCode: "response_too_large"})
			}
			return
		}
		if s.Fence.Check(peer.EndpointID, peer.ConnectionGeneration) != nil || (frame.ConnectionGeneration != "" && frame.ConnectionGeneration != strconv.FormatInt(peer.ConnectionGeneration, 10)) {
			return
		}
		s.Mu.Lock()
		peer.LastSeen = time.Now()
		s.Mu.Unlock()
		if frame.Type == FrameHeartbeat {
			_ = wsjson.Write(ctx, peer.Conn, Frame{Type: FrameHeartbeatAck, ProtocolVersion: ProtocolVersion, ConnectionGeneration: strconv.FormatInt(peer.ConnectionGeneration, 10)})
		}
		if frame.Type == FrameLaunchResponse {
			s.deliverLaunch(peer, frame)
		}
		if frame.Type == FrameOutputResponse {
			s.Mu.Lock()
			if pending, ok := s.pendingOutput[frame.RequestID]; ok {
				delete(s.pendingOutput, frame.RequestID)
				pending.response <- frame
			}
			s.Mu.Unlock()
		}
		if frame.Type == FrameReceipt && frame.Receipt != nil && s.OnReceipt != nil {
			s.OnReceipt(*peer, *frame.Receipt)
		}
		if s.OnFrame != nil {
			s.OnFrame(*peer, frame)
		}
	}
}

// failPendingOutput reports an output-channel failure to requests for one Endpoint.
func (s *Server) failPendingOutput(endpointID string, response protocol.OutputSnapshotResponse) {
	s.Mu.Lock()
	defer s.Mu.Unlock()
	for requestID, pending := range s.pendingOutput {
		if pending.endpointID != endpointID {
			continue
		}
		delete(s.pendingOutput, requestID)
		pending.response <- Frame{Type: FrameOutputResponse, OutputResponse: &response}
	}
}

// SendCommand sends a command only through the current fenced peer.
func (s *Server) SendCommand(ctx context.Context, endpointID string, intentFrame Frame) error {
	peer, err := s.currentPeer(endpointID)
	if err != nil {
		return err
	}
	intentFrame.ConnectionGeneration = strconv.FormatInt(peer.ConnectionGeneration, 10)
	return wsjson.Write(ctx, peer.Conn, intentFrame)
}

// RequestOutput asks an online Endpoint for a bounded output snapshot.
func (s *Server) RequestOutput(ctx context.Context, endpointID string, request protocol.OutputSnapshotRequest) (protocol.OutputSnapshotResponse, error) {
	requestID := security.NewRequestID()
	response := make(chan Frame, 1)
	s.Mu.Lock()
	s.pendingOutput[requestID] = pendingOutputRequest{endpointID: endpointID, response: response}
	s.Mu.Unlock()
	if err := s.SendCommand(ctx, endpointID, Frame{Type: FrameOutputRequest, ProtocolVersion: ProtocolVersion, RequestID: requestID, OutputRequest: &request}); err != nil {
		s.Mu.Lock()
		delete(s.pendingOutput, requestID)
		s.Mu.Unlock()
		return protocol.OutputSnapshotResponse{ErrorCode: "endpoint_offline"}, err
	}
	select {
	case frame := <-response:
		if frame.OutputResponse == nil {
			return protocol.OutputSnapshotResponse{ErrorCode: "invalid_response"}, errors.New("output response is missing")
		}
		return *frame.OutputResponse, nil
	case <-ctx.Done():
		s.Mu.Lock()
		delete(s.pendingOutput, requestID)
		s.Mu.Unlock()
		return protocol.OutputSnapshotResponse{ErrorCode: "endpoint_offline"}, ctx.Err()
	}
}

// RequestRefresh asks an online Endpoint to collect and report a fresh inventory.
func (s *Server) RequestRefresh(ctx context.Context, endpointID, requestID string) error {
	return s.SendCommand(ctx, endpointID, Frame{Type: FrameInventoryRefresh, ProtocolVersion: ProtocolVersion, RequestID: requestID})
}

// IsOnline reports whether an Endpoint has an authoritative, non-expired peer.
func (s *Server) IsOnline(endpointID string, now time.Time) bool {
	peer, err := s.currentPeer(endpointID)
	if err != nil {
		return false
	}
	return s.HeartbeatTimeout <= 0 || now.Sub(peer.LastSeen) <= s.HeartbeatTimeout
}

func (s *Server) currentPeer(endpointID string) (*Peer, error) {
	s.Mu.RLock()
	peer := s.Active[endpointID]
	s.Mu.RUnlock()
	if peer == nil {
		return nil, ErrOffline
	}
	if err := s.Fence.Check(peer.EndpointID, peer.ConnectionGeneration); err != nil {
		return nil, err
	}
	return peer, nil
}

func (s *Server) remove(peer *Peer) {
	s.Mu.Lock()
	defer s.Mu.Unlock()
	if current := s.Active[peer.EndpointID]; current == peer {
		delete(s.Active, peer.EndpointID)
	}
}

// Close closes all active Endpoint connections.
func (s *Server) Close() error {
	s.Mu.Lock()
	peers := make([]*Peer, 0, len(s.Active))
	for _, peer := range s.Active {
		peers = append(peers, peer)
	}
	s.Active = make(map[string]*Peer)
	s.Mu.Unlock()
	for _, peer := range peers {
		_ = peer.Conn.CloseNow()
	}
	return nil
}
