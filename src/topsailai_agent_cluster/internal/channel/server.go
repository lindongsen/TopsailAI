package channel

import (
	"context"
	"crypto/tls"
	"crypto/x509"
	"encoding/json"
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
	OnDisconnect     func(Peer, int64)
	OnReject         func(error)
	OnRejectReason   func(endpointID, certificateIdentity, reason, requestID string)
	RevokedSerials   map[string]bool
	// SharedCertificate relaxes the certificate-to-Endpoint identity binding when
	// every Endpoint presents the same Server certificate. It is opt-in because
	// the binding is a real security property, not a formality.
	SharedCertificate   bool
	pendingOutput       map[string]pendingOutputRequest
	pendingLaunch       map[string]pendingLaunchRequest
	pendingRefresh      map[string]pendingRefreshRequest
	pendingFollow       map[string]pendingFollowRequest
	pendingHistory      map[string]pendingHistoryRequest
	pendingModelCatalog map[string]pendingModelCatalogRequest
}

// pendingOutputRequest tracks one output request so read-limit failures can be reported.
type pendingOutputRequest struct {
	endpointID string
	response   chan Frame
}

// pendingRefreshRequest tracks one forced collection so its committed report can be returned.
type pendingRefreshRequest struct {
	endpointID string
	response   chan Frame
}

// pendingFollowRequest tracks one streaming follow. Unlike a snapshot, a follow
// delivers many chunks before it ends, so it owns a channel of chunk events
// rather than a single response slot.
type pendingFollowRequest struct {
	endpointID string
	events     chan FollowEvent
	// done is closed when the request is released, so the cancellation watcher
	// stops instead of lingering for the lifetime of the process.
	done chan struct{}
}

// FollowEvent is one delivered follow frame: either a chunk or the terminal end.
// Exactly one event carries End, and it is always the last event for its stream,
// so a consumer that stops receiving events without End treats the stream as
// interrupted rather than complete.
type FollowEvent struct {
	Chunk *protocol.OutputChunk
	End   *protocol.OutputEnd
}

// followChunkBuffer bounds how many chunks may wait for one consumer. A consumer
// that falls this far behind is disconnected rather than buffered without limit,
// because an unbounded queue would let one slow reader exhaust Server memory.
const followChunkBuffer = 64

// maxPendingFollow bounds concurrent follow streams per Server so a few operators
// cannot hold every transport slot.
const maxPendingFollow = 64

// channelReadLimit bounds one channel frame so a hostile peer cannot exhaust memory.
const channelReadLimit int64 = 2 << 20

// maxPendingRefresh bounds concurrent forced collections so discovery cannot amplify.
const maxPendingRefresh = 64

// Peer is one currently connected Endpoint.
type Peer struct {
	EndpointID           string
	InstanceID           string
	Hostname             string
	ConnectionGeneration int64
	Initiator            string
	Conn                 *websocket.Conn
	LastSeen             time.Time
}

// NewServer constructs a channel server.
func NewServer(tlsConfig *tls.Config) *Server {
	return &Server{TLSConfig: tlsConfig, Fence: NewFence(), Active: make(map[string]*Peer), HeartbeatTimeout: 30 * time.Second, RevokedSerials: make(map[string]bool), pendingOutput: make(map[string]pendingOutputRequest), pendingRefresh: make(map[string]pendingRefreshRequest), pendingFollow: make(map[string]pendingFollowRequest), pendingHistory: make(map[string]pendingHistoryRequest), pendingModelCatalog: make(map[string]pendingModelCatalogRequest)}
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
	// A shared certificate cannot bind the peer to one Endpoint identity, because
	// every Endpoint presents the same certificate name. The check is skipped only
	// when the operator explicitly enabled the shared-certificate mode; the strict
	// default still requires the certificate to name the claimed Endpoint.
	if certificate != nil && !s.SharedCertificate {
		if err := security.ValidateEndpointIdentity(certificate, hello.EndpointID); err != nil {
			s.sendHelloRejection(r.Context(), conn, hello, "identity_mismatch", err.Error(), certificate)
			s.reject(err)
			return
		}
	}
	// An explicit server initiator means the peer dialed the wrong side: this
	// handler only accepts Endpoint-initiated connections. An empty initiator is
	// the legacy handshake and is treated as Endpoint-initiated.
	if hello.Initiator == InitiatorServer {
		s.sendHelloRejection(r.Context(), conn, hello, "wrong_initiator", "handler requires an endpoint-initiated connection", certificate)
		return
	}
	peer := s.installPeer(hello.EndpointID, hello.InstanceID, hello.Hostname, InitiatorEndpoint, conn)
	ack := Frame{Type: FrameHelloAck, ProtocolVersion: ProtocolVersion, ConnectionGeneration: strconv.FormatInt(peer.ConnectionGeneration, 10), EndpointID: hello.EndpointID}
	if err := wsjson.Write(context.Background(), conn, ack); err != nil {
		s.remove(peer)
		return
	}
	// The Endpoint confirms it adopted this generation. Waiting here means the
	// Server only treats a link as established once both sides agree, which is the
	// same rule the Server-initiated direction uses.
	var attached Frame
	if err := wsjson.Read(r.Context(), conn, &attached); err != nil {
		s.remove(peer)
		return
	}
	if attached.Type != FrameHelloAttached || attached.EndpointID != hello.EndpointID || attached.ConnectionGeneration != ack.ConnectionGeneration {
		s.remove(peer)
		_ = conn.Close(websocket.StatusPolicyViolation, "invalid hello attached")
		return
	}
	go s.readLoop(context.Background(), peer)
}

// installPeer makes a connection authoritative and assigns its generation under
// one lock, so install order and generation order are identical and the newest
// connection always wins. Assigning the generation before the handshake instead
// would let a slower handshake overwrite a newer connection, which is the
// opposite of the required latest-wins behaviour.
func (s *Server) installPeer(endpointID, instanceID, hostname, initiator string, conn *websocket.Conn) *Peer {
	s.Mu.Lock()
	generation := s.Fence.Acquire(endpointID)
	peer := &Peer{EndpointID: endpointID, InstanceID: instanceID, Hostname: hostname, ConnectionGeneration: generation, Initiator: initiator, Conn: conn, LastSeen: time.Now()}
	previous := s.Active[endpointID]
	s.Active[endpointID] = peer
	s.Mu.Unlock()
	if previous != nil && previous.Conn != conn {
		_ = previous.Conn.CloseNow()
	}
	return peer
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
		if frame.Type == FrameHistoryResponse {
			s.deliverHistory(peer, frame)
		}
		if frame.Type == FrameModelCatalogResponse {
			s.deliverModelCatalog(peer, frame)
		}
		if frame.Type == FrameOutputResponse {
			s.Mu.Lock()
			if pending, ok := s.pendingOutput[frame.RequestID]; ok {
				delete(s.pendingOutput, frame.RequestID)
				pending.response <- frame
			}
			s.Mu.Unlock()
		}
		if frame.Type == FrameOutputChunk || frame.Type == FrameOutputEnd {
			s.deliverFollow(peer, frame)
		}
		if frame.Type == FrameReceipt && frame.Receipt != nil && s.OnReceipt != nil {
			s.OnReceipt(*peer, *frame.Receipt)
		}
		if s.OnFrame != nil {
			s.OnFrame(*peer, frame)
		}
		// A forced collection is delivered only after the persistence hook ran, so the
		// waiter observes the committed state rather than the submitted report.
		if frame.Type == FrameInventory && frame.RequestID != "" {
			s.deliverRefresh(peer, frame)
		}
	}
}

// deliverRefresh hands a correlated forced-collection report to its waiting request.
func (s *Server) deliverRefresh(peer *Peer, frame Frame) {
	s.Mu.Lock()
	defer s.Mu.Unlock()
	pending, ok := s.pendingRefresh[frame.RequestID]
	if !ok || pending.endpointID != peer.EndpointID {
		return
	}
	delete(s.pendingRefresh, frame.RequestID)
	pending.response <- frame
}

// deliverFollow hands one chunk or the terminal end to its waiting consumer.
//
// A chunk is delivered without blocking the channel read loop: if the consumer
// has fallen behind the bounded buffer, the follow is terminated with an explicit
// overflow error instead of stalling every other frame on this connection. A
// silent drop would let the operator believe the stream is complete, so the
// consumer always learns that data was lost.
func (s *Server) deliverFollow(peer *Peer, frame Frame) {
	s.Mu.Lock()
	pending, ok := s.pendingFollow[frame.RequestID]
	if !ok || pending.endpointID != peer.EndpointID {
		s.Mu.Unlock()
		return
	}
	s.Mu.Unlock()
	if frame.Type == FrameOutputEnd {
		released, ok := s.releaseFollow(frame.RequestID)
		if !ok {
			return
		}
		end := frame.OutputEnd
		if end == nil {
			end = &protocol.OutputEnd{ErrorCode: "invalid_response", ObservedAtMS: time.Now().UnixMilli()}
		}
		deliverFollowEnd(released.events, end)
		return
	}
	chunk := frame.OutputChunk
	if chunk == nil {
		return
	}
	select {
	case pending.events <- FollowEvent{Chunk: chunk}:
	default:
		// The consumer is too slow to keep up with the provider. Terminating the
		// stream with an explicit code is the only honest option: buffering
		// without limit would exhaust Server memory, and dropping the chunk
		// silently would present a partial stream as complete.
		released, ok := s.releaseFollow(frame.RequestID)
		if !ok {
			return
		}
		deliverFollowEnd(released.events, &protocol.OutputEnd{ErrorCode: "consumer_overflow", ObservedAtMS: time.Now().UnixMilli()})
	}
}

// deliverFollowEnd guarantees the terminal event reaches the consumer.
//
// A plain non-blocking send would drop the end event exactly when the queue is
// full, which is the overflow case that most needs to be reported: the consumer
// would then see neither the missing chunks nor the reason, and would treat a
// truncated stream as a finished one. Discarding the queued chunks is acceptable
// here because the end event already declares that data was lost.
func deliverFollowEnd(events chan FollowEvent, end *protocol.OutputEnd) {
	for {
		select {
		case events <- FollowEvent{End: end}:
			return
		default:
		}
		select {
		case <-events:
		default:
			// The consumer drained the queue concurrently; retry the send.
		}
	}
}

// releaseFollow removes one pending follow and closes its done channel so the
// cancellation watcher stops. It is idempotent, so a disconnect, a terminal
// frame and a cancelled context can all race without double-closing done.
func (s *Server) releaseFollow(requestID string) (pendingFollowRequest, bool) {
	s.Mu.Lock()
	pending, ok := s.pendingFollow[requestID]
	if ok {
		delete(s.pendingFollow, requestID)
	}
	s.Mu.Unlock()
	if ok {
		close(pending.done)
	}
	return pending, ok
}

// failPendingFollow reports a transport failure to every follow for one Endpoint,
// so a disconnected Endpoint never leaves a consumer waiting for chunks that can
// no longer arrive.
func (s *Server) failPendingFollow(endpointID string) {
	s.Mu.Lock()
	requestIDs := make([]string, 0, len(s.pendingFollow))
	for requestID, request := range s.pendingFollow {
		if request.endpointID == endpointID {
			requestIDs = append(requestIDs, requestID)
		}
	}
	s.Mu.Unlock()
	for _, requestID := range requestIDs {
		released, ok := s.releaseFollow(requestID)
		if !ok {
			continue
		}
		deliverFollowEnd(released.events, &protocol.OutputEnd{ErrorCode: "endpoint_offline", ObservedAtMS: time.Now().UnixMilli()})
	}
}

// failPendingRefresh reports a transport failure to every request for one Endpoint.
func (s *Server) failPendingRefresh(endpointID string) {
	s.Mu.Lock()
	defer s.Mu.Unlock()
	for requestID, pending := range s.pendingRefresh {
		if pending.endpointID != endpointID {
			continue
		}
		delete(s.pendingRefresh, requestID)
		pending.response <- Frame{Type: FrameInventory}
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

// RequestFollow starts one streaming output follow and returns its event stream.
//
// The returned channel delivers chunks followed by exactly one terminal end
// event. A consumer that stops receiving events without an end event must treat
// the stream as interrupted rather than complete, because a silent stop would
// present a partial stream as a finished one.
//
// Cancelling ctx releases the pending entry and terminates the stream with a
// cancelled end event, so an operator who stops watching never leaves a provider
// child streaming into a queue nobody reads.
func (s *Server) RequestFollow(ctx context.Context, endpointID string, request protocol.OutputFollowRequest) (<-chan FollowEvent, error) {
	requestID := security.NewRequestID()
	events := make(chan FollowEvent, followChunkBuffer)
	done := make(chan struct{})
	s.Mu.Lock()
	if len(s.pendingFollow) >= maxPendingFollow {
		s.Mu.Unlock()
		return nil, errors.New("follow capacity exceeded")
	}
	s.pendingFollow[requestID] = pendingFollowRequest{endpointID: endpointID, events: events, done: done}
	s.Mu.Unlock()
	if err := s.SendCommand(ctx, endpointID, Frame{Type: FrameOutputFollowRequest, ProtocolVersion: ProtocolVersion, RequestID: requestID, OutputFollowRequest: &request}); err != nil {
		s.releaseFollow(requestID)
		return nil, err
	}
	go func() {
		select {
		case <-ctx.Done():
			released, ok := s.releaseFollow(requestID)
			if !ok {
				return
			}
			deliverFollowEnd(released.events, &protocol.OutputEnd{ErrorCode: "cancelled", ObservedAtMS: time.Now().UnixMilli()})
		case <-done:
		}
	}()
	return events, nil
}

// RequestRefresh asks an online Endpoint to collect and report a fresh inventory.
func (s *Server) RequestRefresh(ctx context.Context, endpointID, requestID string) error {
	return s.SendCommand(ctx, endpointID, Frame{Type: FrameInventoryRefresh, ProtocolVersion: ProtocolVersion, RequestID: requestID})
}

// RequestRefreshAndWait forces one fresh collection and returns the report the
// Server persisted for it, so a caller can prove the data is fresh rather than cached.
func (s *Server) RequestRefreshAndWait(ctx context.Context, endpointID string) (protocol.InventoryReport, error) {
	requestID := security.NewRequestID()
	response := make(chan Frame, 1)
	s.Mu.Lock()
	if len(s.pendingRefresh) >= maxPendingRefresh {
		s.Mu.Unlock()
		return protocol.InventoryReport{}, errors.New("refresh capacity exceeded")
	}
	s.pendingRefresh[requestID] = pendingRefreshRequest{endpointID: endpointID, response: response}
	s.Mu.Unlock()
	if err := s.SendCommand(ctx, endpointID, Frame{Type: FrameInventoryRefresh, ProtocolVersion: ProtocolVersion, RequestID: requestID}); err != nil {
		s.Mu.Lock()
		delete(s.pendingRefresh, requestID)
		s.Mu.Unlock()
		return protocol.InventoryReport{}, err
	}
	select {
	case frame := <-response:
		if frame.Payload == nil {
			return protocol.InventoryReport{}, errors.New("refresh response is missing")
		}
		data, err := json.Marshal(frame.Payload)
		if err != nil {
			return protocol.InventoryReport{}, fmt.Errorf("marshal refresh response: %w", err)
		}
		var report protocol.InventoryReport
		if err := json.Unmarshal(data, &report); err != nil {
			return protocol.InventoryReport{}, fmt.Errorf("decode refresh response: %w", err)
		}
		return report, nil
	case <-ctx.Done():
		s.Mu.Lock()
		delete(s.pendingRefresh, requestID)
		s.Mu.Unlock()
		return protocol.InventoryReport{}, ctx.Err()
	}
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
	current := s.Active[peer.EndpointID]
	authoritative := current == peer
	if authoritative {
		delete(s.Active, peer.EndpointID)
	}
	// Capture the observation time under the lock so a later reconnect cannot be
	// overwritten by this disconnect.
	observedAtMS := time.Now().UnixMilli()
	s.Mu.Unlock()
	if !authoritative {
		return
	}
	// A disconnected Endpoint can never answer a forced collection or a history
	// read, so fail the waiters instead of letting them block until their deadline.
	s.failPendingRefresh(peer.EndpointID)
	s.failPendingHistory(peer.EndpointID)
	s.failPendingModelCatalog(peer.EndpointID)
	// A disconnected Endpoint can never answer a snapshot or a follow either, so
	// those waiters are failed immediately instead of blocking until their own
	// deadline.
	s.failPendingOutput(peer.EndpointID, protocol.OutputSnapshotResponse{ErrorCode: "endpoint_offline"})
	s.failPendingFollow(peer.EndpointID)
	if s.OnDisconnect == nil {
		return
	}
	// Notify outside the channel lock so persistence latency cannot block other peers.
	s.OnDisconnect(*peer, observedAtMS)
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
