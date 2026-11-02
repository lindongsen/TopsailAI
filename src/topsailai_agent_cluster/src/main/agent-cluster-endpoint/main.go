package main

import (
	"context"
	"crypto/tls"
	"encoding/json"
	"fmt"
	"os"
	"os/signal"
	"syscall"
	"time"

	"topsailai_agent_cluster/internal/adapter"
	"topsailai_agent_cluster/internal/channel"
	"topsailai_agent_cluster/internal/config"
	endpointservice "topsailai_agent_cluster/internal/endpoint"
	"topsailai_agent_cluster/internal/logging"
	"topsailai_agent_cluster/internal/protocol"
	"topsailai_agent_cluster/internal/security"
	endpointstorage "topsailai_agent_cluster/internal/storage/endpoint"
)

func main() {
	cfg, err := config.Load(os.Args[1:], "agent-cluster-endpoint")
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
	store, err := endpointstorage.Open(ctx, cfg.DatabasePath)
	if err != nil {
		logger.Error("open endpoint storage", "error", err)
		os.Exit(1)
	}
	if cfg.ChannelAddress == "" {
		_ = store.Close()
		<-ctx.Done()
		return
	}
	var tlsConfig *tls.Config
	if cfg.TLSCertificateFile != "" && cfg.TLSKeyFile != "" {
		tlsConfig, err = security.LoadMTLSConfig(security.MTLSConfig{CAFile: cfg.TLSCAFile, CertificateFile: cfg.TLSCertificateFile, KeyFile: cfg.TLSKeyFile, RevokedSerialsFile: cfg.TLSRevokedSerialsFile}, false)
		if err != nil {
			logger.Error("load mTLS configuration", "error", err)
			_ = store.Close()
			os.Exit(1)
		}
	}
	hostname, hostnameErr := os.Hostname()
	if hostnameErr != nil {
		logger.Warn("resolve endpoint hostname", "error", hostnameErr)
	}
	client := &channel.EndpointClient{EndpointID: cfg.EndpointID, InstanceID: cfg.InstanceID, Hostname: hostname, TLSConfig: tlsConfig, Address: cfg.ChannelAddress}
	if err := client.Dial(ctx, cfg.ChannelAddress); err != nil {
		logger.Error("connect endpoint channel; reconnecting", "error", err)
	}
	if len(cfg.Adapters) == 0 {
		logger.Error("endpoint adapters are required", "error", "AGENT_CLUSTER_ADAPTERS is empty")
		_ = client.Close()
		_ = store.Close()
		os.Exit(1)
	}
	registry := adapter.NewRegistry()
	registered := make(map[string]bool)
	for _, item := range cfg.Adapters {
		if registered[item.ProviderType] {
			continue
		}
		providerType := item.ProviderType
		if err := registerAdapterType(registry, providerType, store); err != nil {
			logger.Error("register adapter provider", "provider_type", providerType, "error", err)
			_ = client.Close()
			_ = store.Close()
			os.Exit(1)
		}
		registered[providerType] = true
	}
	bindings := make([]endpointservice.Binding, 0, len(cfg.Adapters))
	for _, item := range cfg.Adapters {
		instance, err := registry.Configure(ctx, adapter.Config{AdapterID: item.AdapterID, ProviderType: item.ProviderType, Command: item.Command, Args: item.Args, TimeoutMS: item.TimeoutMS, Capabilities: item.Capabilities})
		if err != nil {
			logger.Error("configure adapter", "adapter_id", item.AdapterID, "error", err)
			_ = client.Close()
			_ = store.Close()
			os.Exit(1)
		}
		descriptor, err := instance.Describe(ctx)
		if err != nil {
			logger.Error("describe adapter", "adapter_id", item.AdapterID, "error", err)
			_ = client.Close()
			_ = store.Close()
			os.Exit(1)
		}
		bindings = append(bindings, endpointservice.Binding{AdapterID: item.AdapterID, ProviderType: item.ProviderType, DisplayName: descriptor.DisplayName, Version: descriptor.Version, Capabilities: descriptor.Capabilities, Adapter: instance})
	}
	collector, err := endpointservice.NewCollector(ctx, bindings, 30*time.Second, store)
	if err != nil {
		logger.Error("create collector", "error", err)
		_ = client.Close()
		_ = store.Close()
		os.Exit(1)
	}
	runtime := newRuntimeHooks(logger, cfg.DatabasePath)
	executor, err := endpointservice.NewExecutor(store, registry, func() {
		if runtime.BeforeInvocation != nil {
			runtime.BeforeInvocation()
		}
	})
	if err == nil {
		executor.AdmissionHook = func(hookCtx context.Context, intent protocol.ImmutableIntent, requestHash string) error {
			receipt := protocol.ExecutionReceipt{CommandID: intent.CommandID, RequestHash: requestHash, Phase: protocol.PhaseInvocationStarted, DeliveryBoundary: protocol.DeliveryNotStarted, EffectCertainty: protocol.EffectUnknown, Outcome: "endpoint_admitted"}
			data, marshalErr := json.Marshal(receipt)
			if marshalErr != nil {
				return marshalErr
			}
			if err := client.SendFrame(hookCtx, channel.Frame{Type: channel.FrameReceipt, ProtocolVersion: channel.ProtocolVersion, FrameID: intent.CommandID, RequestID: intent.CommandID, Receipt: &receipt, Payload: json.RawMessage(data)}); err != nil {
				return err
			}
			if err := runtime.announceHold("endpoint_admitted"); err != nil {
				return err
			}
			return runtime.waitForRelease(logger, "endpoint_admitted")
		}
	}
	if err != nil {
		logger.Error("create command executor", "error", err)
		_ = client.Close()
		_ = store.Close()
		os.Exit(1)
	}
	service, err := endpointservice.NewService(endpointservice.ServiceDeps{Collector: collector, Executor: executor, Channel: client, Heartbeater: client, Storage: store, Logger: logger, CollectionInterval: runtime.CollectionInterval, HeartbeatInterval: 5 * time.Second, ReceiptDelay: runtime.ReceiptDelay})
	if err != nil {
		logger.Error("create endpoint service", "error", err)
		_ = client.Close()
		_ = store.Close()
		os.Exit(1)
	}
	if err := service.Run(ctx); err != nil {
		logger.Error("endpoint service stopped", "error", err)
	}
	if err := service.Close(); err != nil {
		logger.Error("close endpoint service", "error", err)
	}
}
