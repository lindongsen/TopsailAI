package channel

import (
	"context"
	"crypto/tls"
	"crypto/x509"
	"encoding/json"
	"errors"
	"fmt"
	"log/slog"
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
	// Logger records follow stream terminations. A follow can end for reasons
	// that never reach the operator as an error, such as a slow consumer or a
	// capacity refusal, so without a log the only evidence that a stream was
	// cut short is the operator's own report. It is optional so a Server built
	// without logging still works.
	Logger *slog.Logger
	// Identity names this Server database. It is reported in the handshake so an
	// Endpoint can tell a restarted Server from a different one, which decides
	// whether recorded receipts may be discarded.
	Identity string
	// SharedCertificate relaxes the certificate-to-Endpoint identity binding when
	// every Endpoint presents the same Server certificate. It is opt-in because
	// the binding is a real security property, not a formality.
	SharedCertificate     bool
	pendingOutput         map[string]pendingOutputRequest
	pendingLaunch         map[string]pendingLaunchRequest
	pendingRefresh        map[string]pendingRefreshRequest
	pendingFollow         map[string]pendingFollowRequest
	pendingHistory        map[string]pendingHistoryRequest
	pendingMessages       map[string]pendingMessagesRequest
	pendingModelCatalog   map[string]pendingModelCatalogRequest
	pendingModelRegistry  map[string]pendingModelRegistryRequest
	pendingProjectCatalog map[string]pendingProjectCatalogRequest
	pendingMetrics        map[string]pendingMetricsRequest
	pendingMetricsBatch   map[string]pendingMetricsBatchRequest
	pendingDetail         map[string]pendingDetailRequest
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

// followChunkBuffer is the minimum number of chunks that may wait for one
// consumer. A consumer that falls this far behind is disconnected rather than
// buffered without limit, because an unbounded queue would let one slow reader
// exhaust Server memory.
//
// It is a floor rather than the whole bound, because the Endpoint delivers one
// frame per record and a requested tail can be far larger than this value. A
// fixed bound smaller than the requested tail made a healthy consumer look like
// a stalled one: the Server filled the queue before the consumer could drain it
// and terminated the stream with consumer_overflow. See followQueueCapacity.
const followChunkBuffer = 64

// followMaxChunkBuffer bounds the derived queue so one reader can never reserve
// unbounded Server memory, however large a tail it requests. The Server clamps a
// requested tail to 10000 lines (internal/server/http.go parseMaxLines), so this
// ceiling covers the largest tail the API accepts plus the headroom below.
const followMaxChunkBuffer = 16384

// followQueueHeadroom is the extra room above the requested tail. The tail is
// delivered as one frame per record, so a queue sized exactly to the tail is
// full the moment the last record is queued, and any consumer cost at all then
// overflows before it can drain. The headroom absorbs that burst boundary.
const followQueueHeadroom = 256

// followQueueCapacity derives the follow event queue capacity from the requested
// tail. A non-positive tail means the caller asked for the provider default, so
// the Server cannot know how many records will arrive and uses the floor. The
// result is always at least followChunkBuffer, because deliverFollowEnd relies on
// a buffered channel to terminate instead of spinning.
func followQueueCapacity(maxLines int) int {
	if maxLines <= 0 {
		return followChunkBuffer
	}
	capacity := maxLines + followQueueHeadroom
	if capacity < followChunkBuffer {
		return followChunkBuffer
	}
	if capacity > followMaxChunkBuffer {
		return followMaxChunkBuffer
	}
	return capacity
}

// maxPendingFollow bounds concurrent follow streams per Server so a few operators
// cannot hold every transport slot.
const maxPendingFollow = 64

// channelReadLimit bounds one channel frame so a hostile peer cannot exhaust memory.
const channelReadLimit int64 = 2 << 20

// maxPendingRefresh bounds concurrent forced collections so discovery cannot amplify.
const maxPendingRefresh = 64

// businessQueueDepth bounds how many business frames one peer may have waiting.
//
// The queue exists so the read loop never performs a blocking business
// operation: a heartbeat acknowledgement must not wait behind a database write.
// It is bounded because an unbounded queue would let one slow peer grow Server
// memory without limit, which is the same reasoning that bounds the follow
// buffer. Sixteen frames is generous for a healthy peer, which sends one
// inventory every few seconds, so the queue only fills when persistence has
// genuinely stalled.
const businessQueueDepth = 16

// Peer is one currently connected Endpoint.
type Peer struct {
	EndpointID           string
	InstanceID           string
	Hostname             string
	ConnectionGeneration int64
	Initiator            string
	Conn                 *websocket.Conn
	LastSeen             time.Time
	// business carries frames from the read loop to this peer's worker. The
	// worker is the only consumer, so frames are handled in arrival order.
	business chan Frame
	// workerDone is closed once to tell the worker to stop. It is a signal, not
	// a join: waiting for a worker stuck in a database write would reintroduce
	// the very stall this design removes.
	workerDone chan struct{}
	// workerStopped records that workerDone was closed. It is a plain bool
	// guarded by Server.Mu rather than a sync.Once or an atomic, because Peer is
	// passed by value to the OnFrame, OnReceipt and OnDisconnect hooks and any
	// type carrying noCopy would make every one of those calls copy a lock.
	workerStopped bool
}

// stopWorker tells this peer's worker to exit, at most once.
//
// The guard is the Server lock because Peer is copied by value into the hooks:
// only the pointer paths stop a worker, so a copied flag is never the one that
// closes the channel.
func (s *Server) stopWorker(peer *Peer) {
	s.Mu.Lock()
	if peer.workerStopped {
		s.Mu.Unlock()
		return
	}
	peer.workerStopped = true
	s.Mu.Unlock()
	close(peer.workerDone)
}

// NewServer constructs a channel server.
func NewServer(tlsConfig *tls.Config) *Server {
	return &Server{TLSConfig: tlsConfig, Fence: NewFence(), Active: make(map[string]*Peer), HeartbeatTimeout: 30 * time.Second, RevokedSerials: make(map[string]bool), pendingOutput: make(map[string]pendingOutputRequest), pendingRefresh: make(map[string]pendingRefreshRequest), pendingFollow: make(map[string]pendingFollowRequest), pendingHistory: make(map[string]pendingHistoryRequest), pendingMessages: make(map[string]pendingMessagesRequest), pendingModelCatalog: make(map[string]pendingModelCatalogRequest), pendingModelRegistry: make(map[string]pendingModelRegistryRequest), pendingProjectCatalog: make(map[string]pendingProjectCatalogRequest), pendingMetrics: make(map[string]pendingMetricsRequest), pendingDetail: make(map[string]pendingDetailRequest)}
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
	ack := Frame{Type: FrameHelloAck, ProtocolVersion: ProtocolVersion, ConnectionGeneration: strconv.FormatInt(peer.ConnectionGeneration, 10), EndpointID: hello.EndpointID, ServerIdentity: s.Identity}
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
	peer := &Peer{EndpointID: endpointID, InstanceID: instanceID, Hostname: hostname, ConnectionGeneration: generation, Initiator: initiator, Conn: conn, LastSeen: time.Now(), business: make(chan Frame, businessQueueDepth), workerDone: make(chan struct{})}
	previous := s.Active[endpointID]
	s.Active[endpointID] = peer
	s.Mu.Unlock()
	// The worker starts before the read loop so the first business frame always
	// has a consumer. It is started here rather than in the read loop because a
	// peer that never receives a business frame still needs a worker ready, and
	// because the worker must outlive the read loop long enough to drain what was
	// already accepted.
	go s.runBusinessWorker(peer)
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
		// The heartbeat acknowledgement is written here, before any business work
		// is even queued, because it is the frame that keeps the link alive.
		// Routing it through the worker would put it behind a database write and
		// make a busy Server look dead to its Endpoints. It is also never queued:
		// a heartbeat every few seconds would otherwise fill the bounded queue
		// during a stall and disconnect the peer this design is meant to protect.
		if frame.Type == FrameHeartbeat {
			_ = wsjson.Write(ctx, peer.Conn, Frame{Type: FrameHeartbeatAck, ProtocolVersion: ProtocolVersion, ConnectionGeneration: strconv.FormatInt(peer.ConnectionGeneration, 10)})
			continue
		}
		if frame.Type == FrameLaunchResponse {
			s.deliverLaunch(peer, frame)
		}
		if frame.Type == FrameHistoryResponse {
			s.deliverHistory(peer, frame)
		}
		if frame.Type == FrameMessagesResponse {
			s.deliverMessages(peer, frame)
		}
		if frame.Type == FrameModelCatalogResponse {
			s.deliverModelCatalog(peer, frame)
		}
		if frame.Type == FrameModelRegistryResponse {
			s.deliverModelRegistry(peer, frame)
		}
		if frame.Type == FrameProjectCatalogResponse {
			s.deliverProjectCatalog(peer, frame)
		}
		if frame.Type == FrameMetricsResponse {
			s.deliverMetrics(peer, frame)
		}
		if frame.Type == FrameMetricsBatchResponse {
			s.deliverMetricsBatch(peer, frame)
		}
		if frame.Type == FrameDetailResponse {
			s.deliverDetail(peer, frame)
		}
		if frame.Type == FrameOutputResponse {
			s.Mu.Lock()
			if pending, ok := s.pendingOutput[frame.RequestID]; ok {
				delete(s.pendingOutput, frame.RequestID)
				pending.response <- frame
			}
			s.Mu.Unlock()
		}
		// A follow frame is fully handled here and must not reach the business
		// queue. A follow tail is one frame per record, so a 300-line tail offers
		// 300 frames to a queue that holds 16, and the overflow branch closes the
		// whole connection. That turned an ordinary tail into an endpoint_offline
		// failure on a healthy Endpoint. Queueing it bought nothing either: the
		// worker's OnFrame hook ignores every frame that is not an inventory
		// report.
		if frame.Type == FrameOutputChunk || frame.Type == FrameOutputEnd {
			s.deliverFollow(peer, frame)
			continue
		}
		// Everything that can block on persistence or on a network write is
		// handed to the peer's worker. The read loop must reach the next
		// wsjson.Read promptly, because that is the only way the next heartbeat
		// is seen at all.
		if !s.enqueueBusiness(peer, frame) {
			return
		}
	}
}

// enqueueBusiness hands one frame to the peer's worker without ever blocking the
// read loop.
//
// A full queue means this peer cannot keep up with its own inbound frames, which
// only happens when persistence has stalled. Closing the connection is the
// honest outcome: the Endpoint reconnects and resends, whereas blocking would
// stall the heartbeat and dropping the frame would leave state silently
// inconsistent.
func (s *Server) enqueueBusiness(peer *Peer, frame Frame) bool {
	select {
	case peer.business <- frame:
		return true
	default:
		_ = peer.Conn.CloseNow()
		return false
	}
}

// runBusinessWorker drains one peer's business queue in arrival order.
//
// The worker is what makes the read loop non-blocking: a database write or an
// acknowledgement send that takes seconds delays only the next business frame of
// this peer, never the heartbeat acknowledgement that keeps the link alive. One
// worker per peer keeps arrival order without any extra sequencing, which
// matters because a receipt and the inventory that follows it are causally
// related.
func (s *Server) runBusinessWorker(peer *Peer) {
	for {
		select {
		case <-peer.workerDone:
			return
		case frame := <-peer.business:
			// A superseded connection must not write business state: the newer
			// connection already owns this Endpoint, and a late write from the
			// old worker would overwrite it with stale data.
			if !s.isAuthoritative(peer) {
				return
			}
			s.handleBusinessFrame(peer, frame)
		}
	}
}

// handleBusinessFrame runs the blocking part of one frame.
func (s *Server) handleBusinessFrame(peer *Peer, frame Frame) {
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

// isAuthoritative reports whether this peer still owns its Endpoint.
func (s *Server) isAuthoritative(peer *Peer) bool {
	s.Mu.RLock()
	defer s.Mu.RUnlock()
	return s.Active[peer.EndpointID] == peer
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
		// The Endpoint is still streaming into a queue nobody will read, so it
		// must be told to stop. Without this the follow would keep one of the
		// Endpoint's follow slots until the follow budget expired. The
		// terminal event is delivered first, because the consumer is waiting for
		// it and the cancel send is bounded but not instantaneous.
		//
		// This is logged because the operator sees a truncated tail with no
		// error of their own making: the provider was healthy and the Server
		// simply could not keep up. Without the line the only explanation
		// available is the terminal code, which names the symptom but not the
		// Endpoint or the stream it belonged to.
		if s.Logger != nil {
			s.Logger.Warn("output follow terminated by slow consumer",
				"endpoint_id", released.endpointID, "request_id", frame.RequestID, "error_code", "consumer_overflow")
		}
		deliverFollowEnd(released.events, &protocol.OutputEnd{ErrorCode: "consumer_overflow", ObservedAtMS: time.Now().UnixMilli()})
		s.cancelEndpointFollow(released.endpointID, frame.RequestID)
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

// cancelEndpointFollow tells the Endpoint to stop one follow whose consumer has
// gone away.
//
// It is called only when the Server abandons a follow while the Endpoint may
// still be streaming: the caller's context was cancelled, or the consumer fell so
// far behind that the stream was terminated. The Endpoint's own terminal frame
// needs no cancel, because that stream has already finished.
//
// The send is best-effort and bounded. A follow whose Endpoint is offline has
// nothing to cancel, and a transport failure here must not delay the terminal
// event the consumer is waiting for, so the error is deliberately not returned.
// The Endpoint also treats an unknown request ID as a no-op, so a cancel that
// races the Endpoint's own exit is harmless.
func (s *Server) cancelEndpointFollow(endpointID, requestID string) {
	if endpointID == "" || requestID == "" {
		return
	}
	ctx, cancel := context.WithTimeout(context.Background(), followCancelTimeout)
	defer cancel()
	_ = s.SendCommand(ctx, endpointID, Frame{Type: FrameOutputFollowCancel, ProtocolVersion: ProtocolVersion, RequestID: requestID})
}

// followCancelTimeout bounds how long a cancel frame may take to reach an
// Endpoint. It is short because the frame carries no payload and the caller is
// already returning to the operator; a cancel that cannot be delivered in this
// window is not worth delaying the terminal event for.
const followCancelTimeout = 2 * time.Second

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
		// The Endpoint's own terminal frame is best-effort, so a disconnect is
		// the only place the Server can state why a stream ended. Without this
		// line the operator sees endpoint_offline on a follow and has no record
		// of which stream it was or when the link went away.
		if s.Logger != nil {
			s.Logger.Warn("output follow terminated by endpoint disconnect",
				"endpoint_id", endpointID, "request_id", requestID, "error_code", "endpoint_offline")
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
	if err := s.SendCommand(ctx, endpointID, Frame{Type: FrameOutputRequest, ProtocolVersion: ProtocolVersion, RequestID: requestID, OutputRequest: &request, EndpointCredential: security.EndpointCredentialFor(ctx), EndpointRequestDigest: security.EndpointRequestDigestFrom(ctx)}); err != nil {
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
// Cancelling ctx releases the pending entry, sends a cancel frame to the
// Endpoint and terminates the stream with a cancelled end event, so an operator
// who stops watching does not leave a provider child streaming into a queue
// nobody reads. The cancel frame is what makes that true: releasing the pending
// entry alone stops delivery here but leaves the Endpoint streaming until its
// follow budget expires.
func (s *Server) RequestFollow(ctx context.Context, endpointID string, request protocol.OutputFollowRequest) (<-chan FollowEvent, error) {
	requestID := security.NewRequestID()
	// The queue is sized from the requested tail, because the Endpoint delivers
	// one frame per record: a fixed queue smaller than the tail overflows a
	// consumer that is keeping up, and reports it as a stalled one.
	events := make(chan FollowEvent, followQueueCapacity(request.MaxLines))
	done := make(chan struct{})
	s.Mu.Lock()
	if len(s.pendingFollow) >= maxPendingFollow {
		s.Mu.Unlock()
		// A capacity refusal is the Server's own limit, so it is logged here
		// rather than left to the caller. The operator sees too_many_follows and
		// cannot tell whether a previous stream leaked or the fleet is simply
		// busy, and the count is the only evidence that distinguishes the two.
		if s.Logger != nil {
			s.Logger.Warn("output follow refused by capacity",
				"endpoint_id", endpointID, "pending_follows", len(s.pendingFollow), "max_pending_follows", maxPendingFollow)
		}
		return nil, ErrFollowCapacity
	}
	s.pendingFollow[requestID] = pendingFollowRequest{endpointID: endpointID, events: events, done: done}
	s.Mu.Unlock()
	if err := s.SendCommand(ctx, endpointID, Frame{Type: FrameOutputFollowRequest, ProtocolVersion: ProtocolVersion, RequestID: requestID, OutputFollowRequest: &request, EndpointCredential: security.EndpointCredentialFor(ctx), EndpointRequestDigest: security.EndpointRequestDigestFrom(ctx)}); err != nil {
		s.releaseFollow(requestID)
		// This path had no log, so a follow that never started left no trace on
		// the Server at all. The operator saw endpoint_offline and the Server log
		// was empty, which made the failure impossible to attribute: the same
		// symptom is produced by a missing peer, a fenced generation and a failed
		// write, and only the error value distinguishes them. The request ID is
		// recorded because it is the only identity that ties this refusal to the
		// operator's own command.
		if s.Logger != nil {
			s.Logger.Warn("output follow request could not be sent",
				"endpoint_id", endpointID, "request_id", requestID, "error", err)
		}
		return nil, err
	}
	go func() {
		select {
		case <-ctx.Done():
			released, ok := s.releaseFollow(requestID)
			if !ok {
				return
			}
			// The Endpoint is still streaming, so it must be told to stop.
			// Releasing the pending entry only stops delivery here; the Endpoint
			// keeps the follow goroutine, its concurrency slot and the provider
			// child until its follow budget expires. The terminal event is
			// delivered first, because the consumer is waiting for it and the
			// cancel send is bounded but not instantaneous.
			deliverFollowEnd(released.events, &protocol.OutputEnd{ErrorCode: "cancelled", ObservedAtMS: time.Now().UnixMilli()})
			s.cancelEndpointFollow(released.endpointID, requestID)
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

// ExpireStalePeers removes and closes authoritative peers that stopped producing
// authenticated frames. Returning the exact peers lets the caller log the
// transition without re-reading mutable channel state.
func (s *Server) ExpireStalePeers(now time.Time) []Peer {
	if s.HeartbeatTimeout <= 0 {
		return nil
	}
	s.Mu.Lock()
	expired := make([]*Peer, 0)
	for endpointID, peer := range s.Active {
		if now.Sub(peer.LastSeen) <= s.HeartbeatTimeout {
			continue
		}
		delete(s.Active, endpointID)
		expired = append(expired, peer)
	}
	s.Mu.Unlock()
	for _, peer := range expired {
		// The worker is stopped before the connection is closed so it cannot
		// begin another frame for an Endpoint that is already being removed.
		s.stopWorker(peer)
		_ = peer.Conn.CloseNow()
	}
	for _, peer := range expired {
		s.finishDisconnect(peer, now.UnixMilli())
	}
	result := make([]Peer, 0, len(expired))
	for _, peer := range expired {
		result = append(result, *peer)
	}
	return result
}

func (s *Server) remove(peer *Peer) {
	// The worker is told to stop before the peer is removed from Active, so a
	// worker that is between frames cannot start a new one after the Endpoint is
	// already gone. It is a signal rather than a join: a worker blocked in a
	// database write must not delay this cleanup, which is the same stall this
	// design removes from the read loop.
	s.stopWorker(peer)
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
	s.finishDisconnect(peer, observedAtMS)
}

// finishDisconnect releases work bound to one peer and publishes its durable
// state transition after that peer has been authoritatively removed.
func (s *Server) finishDisconnect(peer *Peer, observedAtMS int64) {
	// A disconnected Endpoint can never answer a forced collection or a history
	// read, so fail the waiters instead of letting them block until their deadline.
	s.failPendingRefresh(peer.EndpointID)
	s.failPendingHistory(peer.EndpointID)
	s.failPendingMessages(peer.EndpointID)
	s.failPendingModelCatalog(peer.EndpointID)
	s.failPendingModelRegistry(peer.EndpointID)
	s.failPendingProjectCatalog(peer.EndpointID)
	s.failPendingMetrics(peer.EndpointID)
	s.failPendingMetricsBatch(peer.EndpointID)
	s.failPendingDetail(peer.EndpointID)
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
		// Stop the worker explicitly rather than relying on the read loop's
		// deferred remove: Close clears Active first, so an idle worker would
		// otherwise wait forever on a queue nobody will ever fill.
		s.stopWorker(peer)
		_ = peer.Conn.CloseNow()
	}
	return nil
}
