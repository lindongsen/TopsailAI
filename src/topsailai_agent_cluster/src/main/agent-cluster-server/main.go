package main

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"os/signal"
	"syscall"
	"time"

	"topsailai_agent_cluster/internal/channel"
	"topsailai_agent_cluster/internal/config"
	"topsailai_agent_cluster/internal/logging"
	"topsailai_agent_cluster/internal/protocol"
	"topsailai_agent_cluster/internal/security"
	serverapi "topsailai_agent_cluster/internal/server"
	serverstorage "topsailai_agent_cluster/internal/storage/server"
)

// capabilityRevisionUnknown is the revision recorded when no adapter declared one.
const capabilityRevisionUnknown = "unknown"

// inventoryCapabilityRevision returns the capability revision an endpoint
// reported for its adapters.
//
// The endpoint row carries one revision, so the last adapter that declared one
// wins. That mirrors the capability API handler, which builds the same
// descriptor from the same report, so the endpoint table and the capability
// endpoint never disagree about the revision an operator is looking at.
func inventoryCapabilityRevision(report protocol.InventoryReport) string {
	revision := capabilityRevisionUnknown
	for _, summary := range report.Adapters {
		if summary.Capabilities.Revision != "" {
			revision = summary.Capabilities.Revision
		}
	}
	return revision
}

func main() {
	cfg, err := config.Load(os.Args[1:], "agent-cluster-server")
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(2)
	}
	logger, logCloser, err := logging.New(cfg)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
	defer logCloser.Close()
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	store, err := serverstorage.Open(ctx, cfg.DatabasePath)
	if err != nil {
		logger.Error("open server storage", "error", err)
		os.Exit(1)
	}
	// The Server identity names this database, not this process. An Endpoint
	// compares it across reconnects to tell a restarted Server from a different
	// one, because only a different Server makes recorded receipts permanently
	// inapplicable. Reading it here means the value is durable and survives a
	// restart, so a restarted Server still receives the receipts it can apply.
	serverIdentity, err := store.ServerIdentity(ctx)
	if err != nil {
		logger.Error("read server identity", "error", err)
		_ = store.Close()
		os.Exit(1)
	}
	if cfg.TLSCAFile == "" || cfg.TLSCertificateFile == "" || cfg.TLSKeyFile == "" {
		logger.Error("mTLS channel configuration is required")
		_ = store.Close()
		os.Exit(1)
	}
	tlsConfig, err := security.LoadMTLSConfig(security.MTLSConfig{CAFile: cfg.TLSCAFile, CertificateFile: cfg.TLSCertificateFile, KeyFile: cfg.TLSKeyFile, RevokedSerialsFile: cfg.TLSRevokedSerialsFile}, true)
	if err != nil {
		logger.Error("load mTLS configuration", "error", err)
		_ = store.Close()
		os.Exit(1)
	}
	// The direction decides which side dials. In the server-initiated direction
	// the Server dials every configured Endpoint and opens no inbound channel
	// listener, so a deployment can match whichever network path is reachable. In
	// the bidirectional direction it both listens and dials, so neither side has
	// to be reachable from the other for the cluster to converge.
	serverInitiated := cfg.ChannelDirection == config.DirectionServerInitiated
	bidirectional := cfg.ChannelDirection == config.DirectionBidirectional
	dials := serverInitiated || bidirectional
	if dials && len(cfg.EndpointDialAddresses) == 0 {
		logger.Error("endpoint dial addresses are required when the server dials", "error", "AGENT_CLUSTER_SERVER_ENDPOINT_DIAL_ADDRESSES is empty")
		_ = store.Close()
		os.Exit(1)
	}
	channelListenAddress := cfg.ChannelListenAddress
	if serverInitiated {
		channelListenAddress = ""
	}
	channelService := channel.NewServer(tlsConfig)
	channelService.Identity = serverIdentity
	// Follow terminations are recorded by the channel, because a stream can end
	// for reasons the operator never sees as an error: a slow consumer, a
	// capacity refusal, or a disconnect that arrives after the Endpoint's own
	// terminal frame was lost. Without this the only evidence is the operator's
	// report, which names the symptom but not the Endpoint or the stream.
	channelService.Logger = logger
	// A shared certificate cannot bind a connection to one Endpoint identity, so
	// the Server skips that check only when the operator explicitly enabled it.
	channelService.SharedCertificate = cfg.TLSSharedCertificate
	channelService.OnDisconnect = func(peer channel.Peer, observedAtMS int64) {
		applied, err := store.MarkEndpointOffline(context.Background(), peer.EndpointID, peer.InstanceID, observedAtMS)
		if err != nil {
			logger.Error("store endpoint disconnect", "endpoint_id", peer.EndpointID, "instance_id", peer.InstanceID, "connection_generation", peer.ConnectionGeneration, "error", err)
			return
		}
		if !applied {
			logger.Info("skip stale endpoint disconnect", "endpoint_id", peer.EndpointID, "instance_id", peer.InstanceID, "connection_generation", peer.ConnectionGeneration, "observed_at_ms", observedAtMS)
		}
	}
	broker := serverapi.NewEventBroker(128)
	onFrame := func(peer channel.Peer, frame channel.Frame) {
		if frame.Type != channel.FrameInventory {
			return
		}
		data, marshalErr := json.Marshal(frame.Payload)
		if marshalErr != nil {
			logger.Error("marshal inventory frame", "error", marshalErr)
			return
		}
		var report protocol.InventoryReport
		if unmarshalErr := json.Unmarshal(data, &report); unmarshalErr != nil {
			logger.Error("decode inventory frame", "error", unmarshalErr)
			// The endpoint answered, so its identity is still recorded. The
			// revision stays unknown because no adapter declaration was decoded.
			if err := store.UpsertEndpoint(context.Background(), protocol.Endpoint{EndpointID: peer.EndpointID, InstanceID: peer.InstanceID, DisplayName: peer.EndpointID, Hostname: peer.Hostname, ConnectionState: "online", ObservedAtMS: time.Now().UnixMilli(), CapabilityRevision: capabilityRevisionUnknown}, time.Now().UnixMilli()); err != nil {
				logger.Error("store endpoint identity", "endpoint_id", peer.EndpointID, "error", err)
			}
			return
		}
		// The revision is read from the report rather than fixed, because the
		// endpoint row is what the operator sees in the endpoint table and a
		// fixed value would report "unknown" for an endpoint that declared one.
		if err := store.UpsertEndpoint(context.Background(), protocol.Endpoint{EndpointID: peer.EndpointID, InstanceID: peer.InstanceID, DisplayName: peer.EndpointID, Hostname: peer.Hostname, ConnectionState: "online", ObservedAtMS: time.Now().UnixMilli(), CapabilityRevision: inventoryCapabilityRevision(report)}, time.Now().UnixMilli()); err != nil {
			logger.Error("store endpoint identity", "endpoint_id", peer.EndpointID, "error", err)
			return
		}
		committedRevision, changed, represented, storeErr := store.ReplaceInventoryCommitted(context.Background(), peer.EndpointID, report, time.Now().UnixMilli())
		if storeErr != nil {
			logger.Error("store inventory frame", "endpoint_id", peer.EndpointID, "error", storeErr)
			return
		}
		if !represented {
			logger.Error("committed inventory does not represent the submitted report", "endpoint_id", peer.EndpointID, "submitted_revision", report.SnapshotRevision, "committed_revision", committedRevision)
			return
		}
		if changed {
			broker.Publish(peer.EndpointID, committedRevision)
		}
		if ackErr := channelService.SendCommand(context.Background(), peer.EndpointID, channel.Frame{Type: channel.FrameInventoryAck, ProtocolVersion: channel.ProtocolVersion, SnapshotRevision: committedRevision}); ackErr != nil {
			logger.Warn("send inventory acknowledgement", "endpoint_id", peer.EndpointID, "snapshot_revision", committedRevision, "error", ackErr)
		}
	}
	runtime := newRuntimeHooks(logger)
	commandService := &serverapi.CommandService{Store: store, Transport: serverapi.ChannelTransport{Channel: channelService}, DispatchDelay: runtime.DispatchDelay, HoldPhase: runtime.HoldPhase, HoldDir: runtime.HoldDir, Logger: logger, Hold: func(_ string, phase, _ string) error {
		return runtime.waitForHold(logger, phase)
	}}
	onReceipt := func(peer channel.Peer, receipt protocol.ExecutionReceipt) {
		ack := func(ctx context.Context, endpointID string) error {
			return channelService.SendCommand(ctx, endpointID, channel.Frame{Type: channel.FrameReceiptAck, ProtocolVersion: channel.ProtocolVersion, FrameID: receipt.CommandID, RequestID: receipt.CommandID})
		}
		ackSender := serverapi.AckSender(ack)
		if runtime.DropAck {
			ackSender = func(context.Context, string) error { return nil }
		}
		reject := func(ctx context.Context, endpointID string, reason protocol.ReceiptRejection) error {
			return channelService.SendCommand(ctx, endpointID, channel.Frame{Type: channel.FrameReceiptRejected, ProtocolVersion: channel.ProtocolVersion, FrameID: receipt.CommandID, RequestID: receipt.CommandID, ReceiptRejection: reason})
		}
		if err := serverapi.PersistReceiptAndAck(context.Background(), store, receipt, peer, time.Now(), ackSender, reject); err != nil {
			logger.Error("store command receipt", "command_id", receipt.CommandID, "endpoint_id", peer.EndpointID, "error", err)
			return
		}
	}
	// The authenticator is built from configuration before the handler exists,
	// so a mode that cannot be satisfied by the configured credential fails at
	// startup instead of refusing every request at runtime. A runtime refusal
	// would be reported as a wrong credential, which points the operator at the
	// token value rather than at the mode that cannot use it.
	authenticator, err := security.NewCredentialAuthenticator(security.AuthMode(cfg.AuthMode), cfg.AuthToken, cfg.SignatureWindow)
	if err != nil {
		logger.Error("build operator authenticator", "auth_mode", cfg.AuthMode, "error", err)
		_ = store.Close()
		os.Exit(1)
	}
	service, err := serverapi.NewService(serverapi.ServiceDeps{
		APIHandler:           serverapi.NewHandlerWithCredential(store, authenticator, commandService, broker, channelService, channelService),
		ChannelServer:        channelService,
		Storage:              store,
		Logger:               logger,
		APIListenAddress:     cfg.APIListenAddress,
		ChannelListenAddress: channelListenAddress,
		ChannelTLSConfig:     tlsConfig,
		OnChannelFrame:       onFrame,
		OnReceipt:            onReceipt,
	})
	if err != nil {
		logger.Error("create server service", "error", err)
		_ = store.Close()
		os.Exit(1)
	}
	recoveryAtMS := time.Now().UnixMilli()
	recoveredEndpoints, err := store.MarkPersistedEndpointsOffline(ctx, recoveryAtMS)
	if err != nil {
		logger.Error("recover persisted endpoint connection states", "error", err)
		_ = store.Close()
		os.Exit(1)
	}
	if recoveredEndpoints > 0 {
		logger.Info("recovered persisted endpoint connection states", "endpoints_marked_offline", recoveredEndpoints, "offline_since_at_ms", recoveryAtMS)
	}
	// Repair rows that are offline but carry no retention clock. They are
	// unreachable by the expiry predicate, so without this step a legacy row
	// stays forever. It runs after the recovery above so a row that just
	// reconnected already holds a positive clock and is excluded.
	backfilledEndpoints, err := store.BackfillOfflineSince(ctx)
	if err != nil {
		logger.Error("backfill endpoint offline timestamps", "error", err)
		_ = store.Close()
		os.Exit(1)
	}
	if backfilledEndpoints > 0 {
		logger.Info("backfilled endpoint offline timestamps", "endpoints_backfilled", backfilledEndpoints)
	}
	// Record the resolved addresses before serving: without this line a healthy
	// start leaves no trace in the log, so a silent death cannot be told apart
	// from a start that never happened.
	if dials {
		// The dialer runs before serving so the first connection attempt happens
		// during startup rather than after the API is already accepting traffic.
		runEndpointDialer(ctx, logger, channelService, cfg)
	}
	livenessDone := make(chan struct{})
	go func() {
		defer close(livenessDone)
		runEndpointLiveness(ctx, logger, channelService, channelService.HeartbeatTimeout)
	}()
	expiryDone := make(chan struct{})
	go func() {
		defer close(expiryDone)
		runEndpointExpiry(ctx, logger, store, cfg.EndpointExpiry, cfg.CommandRetention, cfg.EndpointDegradedRetention)
	}()
	// The write-liveness watchdog is the only component allowed to end the process
	// on its own. It exists because a measured outage ran for two hours and
	// fifty-six minutes while every write failed and reads kept working, so the API
	// answered and the process looked healthy while every state change was
	// discarded. A Server that cannot persist anything is not serving its purpose,
	// and continuing to run hides that from the operator and from a supervisor that
	// only checks liveness.
	//
	// It exits from this goroutine rather than signalling the main flow, because the
	// main flow is blocked in service.Run and would only observe the condition after
	// a graceful shutdown that may never come. The coding requirement is explicit
	// that a lost write must terminate the process from any thread, so the log is
	// flushed by the logger's own synchronous write and the process ends here.
	writeLivenessDone := make(chan struct{})
	go func() {
		defer close(writeLivenessDone)
		err := runWriteLiveness(ctx, logger, store, cfg.WriteLivenessInterval, cfg.WriteLivenessBudget)
		if err == nil {
			return
		}
		logger.Error("server cannot persist state", "error", err, "budget", cfg.WriteLivenessBudget.String())
		_ = service.Close()
		os.Exit(1)
	}()
	logger.Info("server service starting", "api_listen_address", cfg.APIListenAddress, "channel_listen_address", channelListenAddress, "channel_direction", cfg.ChannelDirection, "database_path", cfg.DatabasePath, "endpoint_expiry", cfg.EndpointExpiry.String())
	runErr := service.Run(ctx)
	stop()
	<-livenessDone
	<-expiryDone
	<-writeLivenessDone
	if runErr != nil {
		// Run returns nil on a graceful shutdown and the listen error when a port
		// cannot be bound, so a non-zero exit is what lets a supervisor or launcher
		// distinguish a failed start from a clean stop.
		logger.Error("server service stopped", "error", runErr)
		_ = service.Close()
		os.Exit(1)
	}
	if err := service.Close(); err != nil {
		logger.Error("close server service", "error", err)
	}
}
