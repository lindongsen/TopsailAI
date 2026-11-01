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
	channelService := channel.NewServer(tlsConfig)
	broker := serverapi.NewEventBroker(128)
	onFrame := func(peer channel.Peer, frame channel.Frame) {
		if frame.Type != channel.FrameInventory {
			return
		}
		if err := store.UpsertEndpoint(context.Background(), protocol.Endpoint{EndpointID: peer.EndpointID, InstanceID: peer.InstanceID, DisplayName: peer.EndpointID, ConnectionState: "online", ObservedAtMS: time.Now().UnixMilli(), CapabilityRevision: "unknown"}, time.Now().UnixMilli()); err != nil {
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
		if storeErr := store.ReplaceInventory(context.Background(), peer.EndpointID, report, time.Now().UnixMilli()); storeErr != nil {
			logger.Error("store inventory frame", "endpoint_id", peer.EndpointID, "error", storeErr)
			return
		}
		broker.Publish(peer.EndpointID, report.SnapshotRevision)
	}
	runtime := newRuntimeHooks(logger)
	commandService := &serverapi.CommandService{Store: store, Transport: serverapi.ChannelTransport{Channel: channelService}, DispatchDelay: runtime.DispatchDelay, HoldPhase: runtime.HoldPhase, HoldDir: runtime.HoldDir, Hold: func(_ string, phase, _ string) error {
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
		APIHandler:           serverapi.NewHandlerWithCommandsAndBrokerAndOutput(store, cfg.AuthToken, commandService, broker, channelService),
		ChannelServer:        channelService,
		Storage:              store,
		Logger:               logger,
		APIListenAddress:     cfg.APIListenAddress,
		ChannelListenAddress: cfg.ChannelListenAddress,
		ChannelTLSConfig:     tlsConfig,
		OnChannelFrame:       onFrame,
		OnReceipt:            onReceipt,
	})
	if err != nil {
		logger.Error("create server service", "error", err)
		_ = store.Close()
		os.Exit(1)
	}
	if err := service.Run(ctx); err != nil {
		logger.Error("server service stopped", "error", err)
	}
	if err := service.Close(); err != nil {
		logger.Error("close server service", "error", err)
	}
}
