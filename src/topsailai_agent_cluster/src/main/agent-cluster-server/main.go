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
		if err := store.UpsertEndpoint(context.Background(), protocol.Endpoint{EndpointID: peer.EndpointID, InstanceID: peer.InstanceID, DisplayName: peer.EndpointID, Hostname: peer.Hostname, ConnectionState: "online", ObservedAtMS: time.Now().UnixMilli(), CapabilityRevision: "unknown"}, time.Now().UnixMilli()); err != nil {
			logger.Error("store endpoint identity", "endpoint_id", peer.EndpointID, "error", err)
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
		if err := serverapi.PersistReceiptAndAck(context.Background(), store, receipt, peer, time.Now(), ackSender); err != nil {
			logger.Error("store command receipt", "command_id", receipt.CommandID, "endpoint_id", peer.EndpointID, "error", err)
			return
		}
	}
	service, err := serverapi.NewService(serverapi.ServiceDeps{
		APIHandler:           serverapi.NewHandlerWithCommandsAndBrokerAndOutputAndRefresh(store, cfg.AuthToken, commandService, broker, channelService, channelService),
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
		runEndpointExpiry(ctx, logger, store, cfg.EndpointExpiry)
	}()
	logger.Info("server service starting", "api_listen_address", cfg.APIListenAddress, "channel_listen_address", channelListenAddress, "channel_direction", cfg.ChannelDirection, "database_path", cfg.DatabasePath, "endpoint_expiry", cfg.EndpointExpiry.String())
	runErr := service.Run(ctx)
	stop()
	<-livenessDone
	<-expiryDone
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
