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
	topsailaiadapter "topsailai_agent_cluster/internal/adapter/topsailai"
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
	// The direction decides which side dials. In the server-initiated direction
	// the Endpoint has no dial address and instead listens for the Server. In the
	// bidirectional direction it does both, so a deployment where neither side can
	// be assumed reachable from the other still converges on one link.
	serverInitiated := cfg.ChannelDirection == config.DirectionServerInitiated
	bidirectional := cfg.ChannelDirection == config.DirectionBidirectional
	listens := serverInitiated || bidirectional
	dials := !serverInitiated
	if dials && cfg.ChannelAddress == "" {
		if bidirectional {
			logger.Error("endpoint channel address is required for the bidirectional direction", "error", "AGENT_CLUSTER_CHANNEL_ADDRESS is empty")
			_ = store.Close()
			os.Exit(1)
		}
		_ = store.Close()
		<-ctx.Done()
		return
	}
	if listens && cfg.EndpointChannelListen == "" {
		logger.Error("endpoint channel listen address is required when the endpoint listens", "error", "AGENT_CLUSTER_ENDPOINT_CHANNEL_LISTEN_ADDR is empty")
		_ = store.Close()
		os.Exit(1)
	}
	// Two TLS configurations are needed because the two roles are not the same:
	// a dialing client verifies the peer name, while a listening server must
	// request and verify the peer certificate. Reusing the client configuration
	// for the listener leaves ClientAuth unset, so the Server certificate is never
	// requested and every Server-dialed connection is rejected.
	var clientTLS *tls.Config
	var acceptorTLS *tls.Config
	if cfg.TLSCertificateFile != "" && cfg.TLSKeyFile != "" {
		clientTLS, err = security.LoadMTLSConfig(security.MTLSConfig{CAFile: cfg.TLSCAFile, CertificateFile: cfg.TLSCertificateFile, KeyFile: cfg.TLSKeyFile, RevokedSerialsFile: cfg.TLSRevokedSerialsFile}, false)
		if err != nil {
			logger.Error("load mTLS configuration", "error", err)
			_ = store.Close()
			os.Exit(1)
		}
		if listens {
			acceptorTLS, err = security.LoadMTLSConfig(security.MTLSConfig{CAFile: cfg.TLSCAFile, CertificateFile: cfg.TLSCertificateFile, KeyFile: cfg.TLSKeyFile, RevokedSerialsFile: cfg.TLSRevokedSerialsFile}, true)
			if err != nil {
				logger.Error("load acceptor mTLS configuration", "error", err)
				_ = store.Close()
				os.Exit(1)
			}
		}
	}
	hostname, hostnameErr := os.Hostname()
	if hostnameErr != nil {
		logger.Warn("resolve endpoint hostname", "error", hostnameErr)
	}
	client := &channel.EndpointClient{EndpointID: cfg.EndpointID, InstanceID: cfg.InstanceID, Hostname: hostname, TLSConfig: clientTLS, Address: cfg.ChannelAddress, Bidirectional: bidirectional}
	if listens {
		// The Endpoint accepts the Server connection, so it must verify the
		// Server certificate itself and reject a revoked one.
		revokedSerials, revokedErr := security.LoadRevokedSerials(cfg.TLSRevokedSerialsFile)
		if revokedErr != nil {
			logger.Error("load revoked certificate serials", "error", revokedErr)
			_ = store.Close()
			os.Exit(1)
		}
		acceptor := &channel.EndpointAcceptor{EndpointID: cfg.EndpointID, ServerName: cfg.ServerName, TLSConfig: acceptorTLS, RevokedSerials: revokedSerials, Client: client, OnReject: func(rejectErr error) {
			logger.Warn("reject server-initiated connection", "error", rejectErr)
		}}
		go func() {
			if serveErr := acceptor.Serve(ctx, cfg.EndpointChannelListen, acceptorTLS); serveErr != nil && ctx.Err() == nil {
				logger.Error("endpoint channel listener stopped", "error", serveErr)
			}
		}()
		logger.Info("endpoint accepting server-initiated connections", "listen_address", cfg.EndpointChannelListen)
	}
	if dials {
		if err := client.Dial(ctx, cfg.ChannelAddress); err != nil {
			logger.Error("connect endpoint channel; reconnecting", "error", err)
		}
	}
	if len(cfg.Adapters) == 0 {
		logger.Error("endpoint adapters are required", "error", "AGENT_CLUSTER_ADAPTERS is empty")
		_ = client.Close()
		_ = store.Close()
		os.Exit(1)
	}
	registry := adapter.NewRegistry()
	// The control action file is Endpoint-local administrative configuration and
	// the only source of ctl. actions. It is loaded before any adapter is
	// configured so a broken file fails startup rather than silently leaving a
	// different action surface in force. An Endpoint without the file advertises
	// no ctl. action at all, which is the fail-closed default.
	var controlActions *topsailaiadapter.ControlActionSet
	if cfg.ControlActionFile != "" {
		controlActions, err = topsailaiadapter.LoadControlActionSet(cfg.ControlActionFile)
		if err != nil {
			logger.Error("load control action file", "path", cfg.ControlActionFile, "error", err)
			_ = client.Close()
			_ = store.Close()
			os.Exit(1)
		}
		logger.Info("loaded control action file", "path", cfg.ControlActionFile, "actions", controlActions.Len(), "names", controlActions.Names())
	} else {
		logger.Info("control action file is not configured; no ctl. action is advertised and every ctl. operation is refused")
	}
	registered := make(map[string]bool)
	for _, item := range cfg.Adapters {
		if registered[item.ProviderType] {
			continue
		}
		providerType := item.ProviderType
		if err := registerAdapterType(registry, providerType, store, controlActions); err != nil {
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
	var commandAllowlist *endpointservice.AllowlistFile
	if cfg.CommandAllowlistFile != "" {
		commandAllowlist, err = endpointservice.LoadAllowlistFile(cfg.CommandAllowlistFile)
		if err != nil {
			logger.Error("load command allowlist", "error", err)
			_ = client.Close()
			_ = store.Close()
			os.Exit(1)
		}
		stopReload, watchErr := commandAllowlist.WatchReload(ctx, func(reloadErr error) {
			if reloadErr != nil {
				logger.Error("reload command allowlist", "error", reloadErr)
				return
			}
			logger.Info("reloaded command allowlist", "entries", commandAllowlist.Allowlist.Len())
		})
		if watchErr != nil {
			logger.Error("watch command allowlist", "error", watchErr)
			_ = client.Close()
			_ = store.Close()
			os.Exit(1)
		}
		defer stopReload()
		logger.Info("loaded command allowlist", "path", cfg.CommandAllowlistFile, "entries", commandAllowlist.Allowlist.Len())
	}
	accessPolicy, err := endpointservice.LoadAccessPolicyDir(cfg.EndpointAccessPolicyDir)
	if err != nil {
		logger.Error("load endpoint access policy", "path", cfg.EndpointAccessPolicyDir, "error", err)
		_ = client.Close()
		_ = store.Close()
		os.Exit(1)
	}
	if cfg.EndpointAccessPolicyDir != "" {
		stopPolicyReload, watchErr := accessPolicy.WatchReload(ctx, func(reloadErr error) {
			if reloadErr != nil {
				logger.Error("reload endpoint access policy", "error", reloadErr)
				return
			}
			logger.Info("reloaded endpoint access policy", "tokens", accessPolicy.Policy.Len())
		})
		if watchErr != nil {
			logger.Error("watch endpoint access policy", "error", watchErr)
			_ = client.Close()
			_ = store.Close()
			os.Exit(1)
		}
		defer stopPolicyReload()
		logger.Info("loaded endpoint access policy", "path", cfg.EndpointAccessPolicyDir, "tokens", accessPolicy.Policy.Len())
	}
	executor, err := endpointservice.NewExecutor(store, registry, func() {
		if runtime.BeforeInvocation != nil {
			runtime.BeforeInvocation()
		}
	})
	if err == nil {
		executor.PolicyHook = func(hookCtx context.Context, intent protocol.ImmutableIntent) error {
			// The access policy decides whether the caller behind this command may
			// exercise this operation on this machine. It runs before the
			// command.exec allowlist because the two answer different questions:
			// the policy answers "may this caller ask", while the allowlist
			// answers "may this argv run". A caller that may not ask must not
			// learn whether its argv would have been allowed.
			if accessPolicy.Policy != nil {
				if permitErr := accessPolicy.Policy.Permit(cfg.EndpointID, security.EndpointToken(hookCtx), intent.Operation); permitErr != nil {
					return permitErr
				}
			}
			if intent.Operation != protocol.OperationCommandExec {
				return nil
			}
			if commandAllowlist == nil {
				return fmt.Errorf("command.exec is not configured: no allowlist file is set")
			}
			var payload protocol.CommandExecRequest
			if unmarshalErr := json.Unmarshal(intent.Payload, &payload); unmarshalErr != nil {
				return fmt.Errorf("decode command.exec payload: %w", unmarshalErr)
			}
			if validateErr := payload.Validate(); validateErr != nil {
				return validateErr
			}
			return commandAllowlist.Allowlist.Permit(payload.Argv)
		}
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
	service, err := endpointservice.NewService(endpointservice.ServiceDeps{Collector: collector, Executor: executor, Channel: client, Heartbeater: client, Storage: store, Logger: logger, CollectionDelay: runtime.CollectionDelay, HeartbeatInterval: 5 * time.Second, ReceiptDelay: runtime.ReceiptDelay, AccessPolicy: accessPolicy.Policy, EndpointID: cfg.EndpointID})
	if err != nil {
		logger.Error("create endpoint service", "error", err)
		_ = client.Close()
		_ = store.Close()
		os.Exit(1)
	}
	if controlActions != nil {
		stopControlReload, watchErr := controlActions.WatchReload(ctx, func(reloadErr error) {
			if reloadErr != nil {
				logger.Error("reload control action file", "error", reloadErr)
				return
			}
			if refreshErr := service.RefreshDescriptors(ctx, "topsailai"); refreshErr != nil {
				logger.Error("publish reloaded control action capabilities", "actions", controlActions.Len(), "names", controlActions.Names(), "error", refreshErr)
				return
			}
			logger.Info("reloaded control action file and scheduled capability inventory", "actions", controlActions.Len(), "names", controlActions.Names())
		})
		if watchErr != nil {
			logger.Error("watch control action file", "error", watchErr)
			_ = client.Close()
			_ = store.Close()
			os.Exit(1)
		}
		defer stopControlReload()
	}
	if err := service.Run(ctx); err != nil {
		logger.Error("endpoint service stopped", "error", err)
	}
	if err := service.Close(); err != nil {
		logger.Error("close endpoint service", "error", err)
	}
}
