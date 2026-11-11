package endpoint

import (
	"context"
	"encoding/json"
	"errors"
	"log/slog"
	"sync"
	"time"

	"topsailai_agent_cluster/internal/channel"
	"topsailai_agent_cluster/internal/protocol"
	"topsailai_agent_cluster/internal/security"
	endpointstorage "topsailai_agent_cluster/internal/storage/endpoint"
)

// ChannelClient is the Endpoint-side transport used by Service.
type ChannelClient interface {
	Read(context.Context) (channel.Frame, error)
	SendFrame(context.Context, channel.Frame) error
	Close() error
}

// ReconnectingChannel reconnects an Endpoint channel after transport loss.
type ReconnectingChannel interface {
	ChannelClient
	Reconnect(context.Context) error
}

// ReadyChannel reports whether the authenticated transport is ready for delivery.
type ReadyChannel interface {
	Ready() bool
}

// Heartbeater maintains channel liveness for a service lifetime.
type Heartbeater interface {
	RunHeartbeat(context.Context, time.Duration) error
}

// ReportCollector collects the latest complete Endpoint inventory.
type ReportCollector interface {
	Collect(context.Context, int64) (protocol.InventoryReport, error)
}

// DescriptorRefresher refreshes adapter descriptors without running discovery.
type DescriptorRefresher interface {
	RefreshDescriptors(context.Context, string, int64) (protocol.InventoryReport, error)
}

// CommandExecutor executes an immutable command through Endpoint-local policy.
type CommandExecutor interface {
	Execute(context.Context, protocol.ImmutableIntent, string) (protocol.ExecutionReceipt, error)
}

// OutputReader reads bounded provider output snapshots.
type OutputReader interface {
	ReadOutput(context.Context, protocol.OutputSnapshotRequest) (protocol.OutputSnapshotResponse, error)
}

// OutputFollower streams provider output records until the consumer stops.
// It is a separate optional interface so an Endpoint whose adapter cannot stream
// reports the capability as unsupported instead of degrading a follow into a
// snapshot that never updates.
type OutputFollower interface {
	FollowOutput(context.Context, protocol.OutputFollowRequest, func(protocol.OutputChunk) error) error
}

const defaultCollectionDelay = 5 * time.Second

// inventoryRetryDelay bounds how long a committed inventory acknowledgement may
// be absent before the Endpoint retries the same immutable revision.
const inventoryRetryDelay = 5 * time.Second

// maxConcurrentFollows bounds how many output follows one Endpoint streams at
// once. Each follow holds a provider child process and a transport slot, so an
// unbounded count would let a few operators starve command and heartbeat
// delivery. A follow beyond this bound is rejected instead of queued, because a
// queued follow would silently start late and the operator would believe the
// stream began when it did not.
const maxConcurrentFollows = 8

// ServiceDeps contains explicit dependencies for the Endpoint lifecycle.
type ServiceDeps struct {
	Collector         ReportCollector
	Executor          CommandExecutor
	Channel           ChannelClient
	Heartbeater       Heartbeater
	Storage           *endpointstorage.Store
	Logger            *slog.Logger
	CollectionDelay   time.Duration
	HeartbeatInterval time.Duration
	ReceiptDelay      time.Duration
	// AccessPolicy decides which caller may exercise which operation on this
	// Endpoint. A nil value permits every caller, which is the state of an
	// Endpoint that was never pointed at a policy directory.
	AccessPolicy *AccessPolicy
	// EndpointID is this Endpoint's own identity, used to evaluate the endpoints
	// declaration in a policy file. The Endpoint knows its own identity, so the
	// comparison needs no claim from the caller.
	EndpointID string
}

// Service owns Endpoint collection, channel handling, and graceful shutdown.
type Service struct {
	collector         ReportCollector
	executor          CommandExecutor
	channel           ChannelClient
	heartbeat         Heartbeater
	storage           *endpointstorage.Store
	logger            *slog.Logger
	collectionDelay   time.Duration
	heartbeatInterval time.Duration
	receiptDelay      time.Duration
	accessPolicy      *AccessPolicy
	endpointID        string
	cancel            context.CancelFunc
	wg                sync.WaitGroup
	closeOnce         sync.Once
	closeErr          error
	receiptsMu        sync.Mutex
	pendingReceipts   map[string]protocol.ExecutionReceipt
	followMu          sync.Mutex
	activeFollows     map[string]context.CancelFunc
	followSlots       chan struct{}
	inventoryTrigger  chan struct{}
	inventoryMu       sync.Mutex
	pendingInventory  *protocol.InventoryReport
}

// NewService constructs an Endpoint lifecycle service from explicit dependencies.
func NewService(deps ServiceDeps) (*Service, error) {
	if deps.Collector == nil || deps.Channel == nil || deps.Storage == nil {
		return nil, errors.New("collector, channel, and storage are required")
	}
	if deps.CollectionDelay <= 0 {
		deps.CollectionDelay = defaultCollectionDelay
	}
	if deps.Heartbeater != nil && deps.HeartbeatInterval <= 0 {
		deps.HeartbeatInterval = 5 * time.Second
	}
	return &Service{collector: deps.Collector, executor: deps.Executor, channel: deps.Channel, heartbeat: deps.Heartbeater, storage: deps.Storage, logger: deps.Logger, collectionDelay: deps.CollectionDelay, heartbeatInterval: deps.HeartbeatInterval, receiptDelay: deps.ReceiptDelay, accessPolicy: deps.AccessPolicy, endpointID: deps.EndpointID, pendingReceipts: make(map[string]protocol.ExecutionReceipt), activeFollows: make(map[string]context.CancelFunc), followSlots: make(chan struct{}, maxConcurrentFollows), inventoryTrigger: make(chan struct{}, 1)}, nil
}

// RefreshDescriptors updates cached capabilities for one provider and schedules
// immediate publication of the resulting inventory without provider discovery.
func (s *Service) RefreshDescriptors(ctx context.Context, providerType string) error {
	refresher, ok := s.collector.(DescriptorRefresher)
	if !ok {
		return errors.New("collector does not support descriptor refresh")
	}
	report, err := refresher.RefreshDescriptors(ctx, providerType, time.Now().UnixMilli())
	if err != nil {
		return err
	}
	s.rememberInventory(report)
	select {
	case s.inventoryTrigger <- struct{}{}:
	default:
	}
	return nil
}

func (s *Service) rememberInventory(report protocol.InventoryReport) {
	s.inventoryMu.Lock()
	defer s.inventoryMu.Unlock()
	if s.pendingInventory == nil || report.SnapshotRevision > s.pendingInventory.SnapshotRevision {
		copy := report
		s.pendingInventory = &copy
	}
}

func (s *Service) acknowledgeInventory(revision int64) {
	s.inventoryMu.Lock()
	defer s.inventoryMu.Unlock()
	if s.pendingInventory != nil && revision >= s.pendingInventory.SnapshotRevision {
		s.pendingInventory = nil
	}
}

func (s *Service) sendPendingInventory(ctx context.Context) {
	s.inventoryMu.Lock()
	if s.pendingInventory == nil {
		s.inventoryMu.Unlock()
		return
	}
	report := *s.pendingInventory
	s.inventoryMu.Unlock()
	payload, err := json.Marshal(report)
	if err != nil {
		s.logError("marshal inventory", err)
		return
	}
	if err := s.channel.SendFrame(ctx, channel.Frame{Type: channel.FrameInventory, ProtocolVersion: channel.ProtocolVersion, Payload: json.RawMessage(payload), SnapshotRevision: report.SnapshotRevision}); err != nil {
		s.logTransportError("publish inventory", err)
	}
}

// Run starts all Endpoint loops and waits until the context is cancelled.
func (s *Service) Run(ctx context.Context) error {
	if ctx == nil {
		return errors.New("context is required")
	}
	runCtx, cancel := context.WithCancel(ctx)
	s.cancel = cancel
	loopCount := 5
	if s.heartbeat != nil {
		loopCount++
	}
	s.wg.Add(loopCount)
	go s.collectionLoop(runCtx)
	go s.inventoryRetryLoop(runCtx)
	go s.channelLoop(runCtx)
	go s.resendRecordedReceipts(runCtx)
	go s.recoverAcceptedCommands(runCtx)
	if s.heartbeat != nil {
		go s.heartbeatLoop(runCtx)
	}
	<-runCtx.Done()
	cancel()
	// Cancel active follows before waiting: a follow holds a provider child
	// process, so waiting first would block shutdown until the operator stops
	// watching.
	s.stopFollows()
	_ = s.channel.Close()
	s.wg.Wait()
	return nil
}

func (s *Service) recoverAcceptedCommands(ctx context.Context) {
	defer s.wg.Done()
	s.loggerInfo("begin accepted command recovery")
	if !s.waitForChannelReady(ctx) {
		s.loggerInfo("accepted command recovery stopped before channel ready")
		return
	}
	s.loggerInfo("accepted command recovery channel ready")
	entries, err := s.storage.ListAcceptedCommands(ctx)
	if err != nil {
		s.logError("load accepted commands for recovery", err)
		return
	}
	s.loggerInfo("accepted command recovery loaded", "count", len(entries))
	for _, entry := range entries {
		var intent protocol.ImmutableIntent
		if err := json.Unmarshal([]byte(entry.IntentJSON), &intent); err != nil {
			s.logError("decode accepted command for recovery "+entry.CommandID, err)
			continue
		}
		s.loggerInfo("recover accepted command", "command_id", entry.CommandID, "phase", string(entry.Phase))
		s.executeFrame(ctx, channel.Frame{Type: channel.FrameCommand, FrameID: entry.CommandID, Intent: &intent})
		s.loggerInfo("recover accepted command complete", "command_id", entry.CommandID, "phase", string(entry.Phase))
	}
}

func (s *Service) waitForChannelReady(ctx context.Context) bool {
	readyChannel, ok := s.channel.(ReadyChannel)
	if !ok {
		return true
	}
	ticker := time.NewTicker(25 * time.Millisecond)
	defer ticker.Stop()
	for {
		if readyChannel.Ready() {
			return true
		}
		select {
		case <-ctx.Done():
			return false
		case <-ticker.C:
		}
	}
}

func (s *Service) resendRecordedReceipts(ctx context.Context) {
	defer s.wg.Done()
	// Recorded receipts must not be resent before the connection exists: the
	// send would fail with ErrOffline and every restart would log a spurious
	// transport error. The sibling recoverAcceptedCommands loop gates on the
	// same helper.
	if !s.waitForChannelReady(ctx) {
		s.loggerInfo("recorded receipt resend stopped before channel ready")
		return
	}
	s.resendPendingReceipts(ctx)
}

// waitForAttachedChannel blocks until the channel reports an attached
// connection, or the context is cancelled. It is used in the server-initiated
// direction, where the Endpoint cannot dial and must wait for the Server.
func (s *Service) waitForAttachedChannel(ctx context.Context) bool {
	readyChannel, ok := s.channel.(ReadyChannel)
	if !ok {
		return false
	}
	ticker := time.NewTicker(200 * time.Millisecond)
	defer ticker.Stop()
	for {
		if readyChannel.Ready() {
			return true
		}
		select {
		case <-ctx.Done():
			return false
		case <-ticker.C:
		}
	}
}

func (s *Service) resendPendingReceipts(ctx context.Context) {
	receipts, err := s.storage.ListRecordedReceipts(ctx)
	if err != nil {
		s.logError("load recorded receipts", err)
		return
	}
	for _, receipt := range receipts {
		data, err := json.Marshal(receipt)
		if err != nil {
			s.logError("marshal recorded receipt", err)
			continue
		}
		s.receiptsMu.Lock()
		s.pendingReceipts[receipt.CommandID] = receipt
		s.receiptsMu.Unlock()
		if err := s.channel.SendFrame(ctx, channel.Frame{Type: channel.FrameReceipt, ProtocolVersion: channel.ProtocolVersion, FrameID: receipt.CommandID, Receipt: &receipt, Payload: json.RawMessage(data)}); err != nil {
			s.logTransportError("resend recorded receipt", err)
		}
	}
}

func (s *Service) heartbeatLoop(ctx context.Context) {
	defer s.wg.Done()
	if err := s.heartbeat.RunHeartbeat(ctx, s.heartbeatInterval); err != nil && ctx.Err() == nil {
		s.logError("run heartbeat", err)
	}
}

func (s *Service) collectionLoop(ctx context.Context) {
	defer s.wg.Done()
	collect := func() {
		report, err := s.collector.Collect(ctx, time.Now().UnixMilli())
		if err != nil {
			if ctx.Err() != nil {
				s.loggerInfo("inventory collection aborted")
				return
			}
			s.logError("collect inventory", err)
			return
		}
		s.rememberInventory(report)
		s.sendPendingInventory(ctx)
	}
	if !s.waitForChannelReady(ctx) {
		s.loggerInfo("inventory collection stopped before channel ready")
		return
	}
	collect()
	for {
		timer := time.NewTimer(s.collectionDelay)
		select {
		case <-ctx.Done():
			timer.Stop()
			return
		case <-s.inventoryTrigger:
			timer.Stop()
			s.sendPendingInventory(ctx)
		case <-timer.C:
			collect()
		}
	}
}

func (s *Service) inventoryRetryLoop(ctx context.Context) {
	defer s.wg.Done()
	ticker := time.NewTicker(inventoryRetryDelay)
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
			s.sendPendingInventory(ctx)
		}
	}
}

func (s *Service) channelLoop(ctx context.Context) {
	defer s.wg.Done()
	for {
		frame, err := s.channel.Read(ctx)
		if err != nil {
			if ctx.Err() != nil {
				return
			}
			s.logTransportError("read channel frame", err)
			reconnecting, ok := s.channel.(ReconnectingChannel)
			if !ok {
				return
			}
			for delay := time.Second; ; {
				if ctx.Err() != nil {
					return
				}
				s.loggerInfo("reconnect endpoint channel", "delay", delay.String())
				timer := time.NewTimer(delay)
				select {
				case <-ctx.Done():
					timer.Stop()
					return
				case <-timer.C:
				}
				if reconnectErr := reconnecting.Reconnect(ctx); reconnectErr == nil {
					s.loggerInfo("endpoint channel reconnected")
					s.resendPendingReceipts(ctx)
					s.sendPendingInventory(ctx)
					break
				} else if errors.Is(reconnectErr, channel.ErrAwaitingServerDial) {
					// The Server dials in this direction, so the Endpoint cannot
					// reconnect by itself. It waits for the acceptor to attach a
					// new connection instead of logging a failure it cannot fix.
					s.loggerInfo("endpoint waits for a server-initiated connection")
					if !s.waitForAttachedChannel(ctx) {
						return
					}
					s.resendPendingReceipts(ctx)
					s.sendPendingInventory(ctx)
					break
				} else {
					s.logError("reconnect endpoint channel", reconnectErr)
				}
				if delay < 10*time.Second {
					delay *= 2
					if delay > 10*time.Second {
						delay = 10 * time.Second
					}
				}
			}
			continue
		}
		switch frame.Type {
		case channel.FrameInventoryAck:
			s.acknowledgeInventory(frame.SnapshotRevision)
		case channel.FrameReceiptAck:
			key := frame.FrameID
			if key == "" {
				key = frame.RequestID
			}
			s.receiptsMu.Lock()
			delete(s.pendingReceipts, key)
			s.receiptsMu.Unlock()
		case channel.FrameInventoryRefresh:
			s.publishRefresh(ctx, frame.RequestID)
		case channel.FrameCommand:
			s.executeFrame(ctx, frame)
		case channel.FrameLaunchRequest:
			s.launchFrame(ctx, frame)
		case channel.FrameHistoryRequest:
			s.historyFrame(ctx, frame)
		case channel.FrameMessagesRequest:
			s.messagesFrame(ctx, frame)
		case channel.FrameModelCatalogRequest:
			s.modelCatalogFrame(ctx, frame)
		case channel.FrameOutputRequest:
			s.outputFrame(ctx, frame)
		case channel.FrameOutputFollowRequest:
			s.startFollow(ctx, frame)
		}
	}
}

func (s *Service) publishRefresh(ctx context.Context, requestID string) {
	report, err := s.collector.Collect(ctx, time.Now().UnixMilli())
	if err != nil {
		// Same rule as the periodic loop: a cancelled cycle is an aborted
		// collection, not a failure. The Server correlates the reply by request
		// ID and will fail the request on its own deadline, so logging an ERROR
		// here would only make a healthy shutdown look broken.
		if ctx.Err() != nil {
			s.loggerInfo("refresh inventory aborted")
			return
		}
		s.logError("refresh inventory", err)
		return
	}
	s.rememberInventory(report)
	payload, err := json.Marshal(report)
	if err != nil {
		s.logError("marshal refreshed inventory", err)
		return
	}
	if err := s.channel.SendFrame(ctx, channel.Frame{Type: channel.FrameInventory, ProtocolVersion: channel.ProtocolVersion, RequestID: requestID, Payload: json.RawMessage(payload), SnapshotRevision: report.SnapshotRevision}); err != nil {
		s.logTransportError("publish refreshed inventory", err)
	}
}

func (s *Service) outputFrame(ctx context.Context, frame channel.Frame) {
	// The policy check runs before the adapter is consulted, so a refused caller
	// cannot infer from the response whether this Endpoint has an output-capable
	// adapter or a reachable session.
	if err := s.permitOperation(frame, protocol.OperationOutputRead); err != nil {
		response := protocol.OutputSnapshotResponse{ErrorCode: s.refuseFrame(ctx, frame, protocol.OperationOutputRead, err), ObservedAtMS: time.Now().UnixMilli()}
		_ = s.channel.SendFrame(ctx, channel.Frame{Type: channel.FrameOutputResponse, ProtocolVersion: channel.ProtocolVersion, RequestID: frame.RequestID, OutputResponse: &response})
		return
	}
	reader, ok := s.executor.(OutputReader)
	if !ok || frame.OutputRequest == nil {
		response := protocol.OutputSnapshotResponse{ErrorCode: "unsupported", ObservedAtMS: time.Now().UnixMilli()}
		_ = s.channel.SendFrame(ctx, channel.Frame{Type: channel.FrameOutputResponse, ProtocolVersion: channel.ProtocolVersion, RequestID: frame.RequestID, OutputResponse: &response})
		return
	}
	response, err := reader.ReadOutput(ctx, *frame.OutputRequest)
	if err != nil && response.ErrorCode == "" {
		response.ErrorCode = "provider_error"
	}
	_ = s.channel.SendFrame(ctx, channel.Frame{Type: channel.FrameOutputResponse, ProtocolVersion: channel.ProtocolVersion, RequestID: frame.RequestID, OutputResponse: &response})
}

func (s *Service) executeFrame(ctx context.Context, frame channel.Frame) {
	if s.executor == nil || frame.Intent == nil {
		return
	}
	// The caller token travels in the context so the executor policy hook can
	// decide whether this token may exercise this operation. It is attached here
	// rather than passed as a parameter because the executor already threads a
	// context through every hop, and the token is a credential no layer between
	// the frame and the policy hook interprets.
	ctx = security.WithEndpointToken(ctx, frame.EndpointToken)
	hash, err := protocol.CanonicalHash(*frame.Intent)
	if err != nil {
		s.logError("hash command intent", err)
		return
	}
	receipt, err := s.executor.Execute(ctx, *frame.Intent, hash)
	if err != nil {
		s.logError("execute command", err)
	}
	// A receipt without a command ID cannot be persisted by the Server, so
	// publishing it would leave the command non-terminal forever. Treat it as
	// an internal error instead of emitting an unusable frame.
	if receipt.CommandID == "" {
		s.logError("execute command", errors.New("executor returned a receipt without a command ID"))
		return
	}
	if s.receiptDelay > 0 {
		timer := time.NewTimer(s.receiptDelay)
		select {
		case <-ctx.Done():
			timer.Stop()
			return
		case <-timer.C:
		}
	}
	data, marshalErr := json.Marshal(receipt)
	if marshalErr != nil {
		s.logError("marshal command receipt", marshalErr)
		return
	}
	s.receiptsMu.Lock()
	s.pendingReceipts[receipt.CommandID] = receipt
	s.receiptsMu.Unlock()
	for attempt := 0; attempt < 3; attempt++ {
		if sendErr := s.channel.SendFrame(ctx, channel.Frame{Type: channel.FrameReceipt, ProtocolVersion: channel.ProtocolVersion, FrameID: receipt.CommandID, RequestID: frame.RequestID, Receipt: &receipt, Payload: json.RawMessage(data)}); sendErr != nil {
			s.logTransportError("publish command receipt", sendErr)
			return
		}
		select {
		case <-ctx.Done():
			return
		case <-time.After(100 * time.Millisecond):
		}
		s.receiptsMu.Lock()
		_, pending := s.pendingReceipts[receipt.CommandID]
		s.receiptsMu.Unlock()
		if !pending {
			return
		}
	}
}

func (s *Service) loggerInfo(message string, args ...any) {
	if s.logger != nil {
		s.logger.Info(message, args...)
	}
}

func (s *Service) loggerWarn(message string, args ...any) {
	if s.logger != nil {
		s.logger.Warn(message, args...)
	}
}

func (s *Service) logError(message string, err error) {
	if s.logger != nil {
		s.logger.Error(message, "error", err)
	}
}

// logTransportError reports a transport failure at WARN when the channel is
// merely offline. An offline channel is a connectivity state, not a failure of
// the operation: the Server keeps the last committed state and the next cycle
// retries, so logging it at ERROR made a healthy restart look broken.
func (s *Service) logTransportError(message string, err error) {
	if errors.Is(err, channel.ErrOffline) {
		s.loggerWarn(message+" deferred until the channel is ready", "error", err)
		return
	}
	s.logError(message, err)
}

// Close cancels active loops, waits for them, and closes transport and storage.
func (s *Service) Close() error {
	s.closeOnce.Do(func() {
		if s.cancel != nil {
			s.cancel()
		}
		_ = s.channel.Close()
		s.wg.Wait()
		if err := s.storage.Close(); err != nil {
			s.closeErr = err
		}
	})
	return s.closeErr
}
