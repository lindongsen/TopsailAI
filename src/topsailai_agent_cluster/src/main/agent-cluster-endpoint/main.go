package main

import (
	"context"
	"crypto/tls"
	"encoding/json"
	"fmt"
	"log/slog"
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
	// The direction decides which side dials. In the server-initiated direction
	// the Endpoint has no dial address and instead listens for the Server. In the
	// bidirectional direction it does both, so a deployment where neither side can
	// be assumed reachable from the other still converges on one link.
	serverInitiated := cfg.ChannelDirection == config.DirectionServerInitiated
	bidirectional := cfg.ChannelDirection == config.DirectionBidirectional
	listens := serverInitiated || bidirectional
	dials := !serverInitiated
	// A single address and an ordered list are two spellings of one setting. The
	// list wins when both are present, because it is the more specific
	// declaration, and folding them here keeps every later stage reading one
	// value instead of two.
	dialAddresses := cfg.ChannelAddresses
	if len(dialAddresses) == 0 && cfg.ChannelAddress != "" {
		dialAddresses = []string{cfg.ChannelAddress}
	}
	if dials && len(dialAddresses) == 0 {
		if bidirectional {
			logger.Error("endpoint channel address is required for the bidirectional direction", "error", "AGENT_CLUSTER_ENDPOINT_CHANNEL_ADDRESS and AGENT_CLUSTER_ENDPOINT_CHANNEL_ADDRESSES are empty")
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
	client := &channel.EndpointClient{EndpointID: cfg.EndpointID, InstanceID: cfg.InstanceID, Hostname: hostname, TLSConfig: clientTLS, Address: cfg.ChannelAddress, Addresses: dialAddresses, Bidirectional: bidirectional, HeartbeatAckTimeout: cfg.HeartbeatAckTimeout, UnhealthyWindow: cfg.UnhealthyWindow, OnAttemptFailure: func(address string, attemptErr error) {
		// A failed attempt is logged even when a later address succeeds, because a
		// silent walk leaves the operator unable to tell "the first Server is down"
		// from "the first Server was never configured". The walk continues, so this
		// is a warning rather than an error.
		logger.Warn("endpoint channel address refused", "address", address, "error", attemptErr)
	}, OnServerUnhealthy: func(unacknowledged time.Duration) {
		// The decision is logged before the connection is closed, because the
		// reconnect that follows is otherwise indistinguishable from a Server that
		// was restarted or killed. Without this line an operator cannot tell that
		// the Endpoint gave up on a Server that was still running.
		logger.Error("heartbeat acknowledgement timed out", "unacknowledged", unacknowledged.String(), "window", cfg.UnhealthyWindow.String())
	}}
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
		if err := client.DialAll(ctx, dialAddresses); err != nil {
			logger.Error("connect endpoint channel; reconnecting", "error", err)
		}
	}
	// A zero-Adapter Endpoint is a supported state, not a startup failure. It
	// connects, reports health and advertises no resource, so an operator can
	// verify the channel and the deployment before any Adapter is configured.
	// Exiting here would make the first step of a rollout impossible to observe.
	if len(cfg.Adapters) == 0 {
		logger.Info("endpoint has no configured adapter; no resource is advertised and every command is refused")
	}
	registry := adapter.NewRegistry()
	// The adapter document is the only source of ctl. capabilities. The Endpoint
	// no longer reads an Endpoint-local catalog: the provider that implements a
	// control action declares what the action is, and the operator's adapter
	// document decides which actions this node serves. An adapter document that
	// names no ctl. capability therefore advertises none, which is the fail-closed
	// default and keeps the action surface a deployment decision.
	// The Endpoint ships exactly one adapter implementation, so it is registered
	// once and never selected by configuration. A configured provider type is
	// validated against that one name below; it cannot choose an implementation
	// because there is nothing to choose between.
	if err := registerAdapter(registry, store); err != nil {
		logger.Error("register adapter", "error", err)
		_ = client.Close()
		_ = store.Close()
		os.Exit(1)
	}
	for _, item := range cfg.Adapters {
		if err := validateProviderType(item.ProviderType); err != nil {
			logger.Error("validate adapter provider type", "adapter_id", item.AdapterID, "provider_type", item.ProviderType, "error", err)
			_ = client.Close()
			_ = store.Close()
			os.Exit(1)
		}
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
	cacheExpiry, err := sourceCacheExpiry()
	if err != nil {
		logger.Error("load source cache expiry", "error", err)
		_ = client.Close()
		_ = store.Close()
		os.Exit(1)
	}
	collector, err := endpointservice.NewCollectorWithOptions(ctx, bindings, 30*time.Second, store, endpointservice.CollectorOptions{SourceCacheExpiry: cacheExpiry, LogCacheDeletion: func(adapterID string) {
		logger.Info("deleted expired source cache", "adapter_id", adapterID, "retention", cacheExpiry.String())
	}})
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
			// The reload path logs the warnings before the token count, because a
			// reload is the moment an operator expects feedback on the file they
			// just edited. Logging the count first would put the reassuring line
			// ahead of the diagnostic that explains why one line grants nothing.
			logAccessPolicyWarnings(logger, "reload endpoint access policy warning", accessPolicy.Policy)
			logger.Info("reloaded endpoint access policy", "tokens", accessPolicy.Policy.Len())
		})
		if watchErr != nil {
			logger.Error("watch endpoint access policy", "error", watchErr)
			_ = client.Close()
			_ = store.Close()
			os.Exit(1)
		}
		defer stopPolicyReload()
		logAccessPolicyWarnings(logger, "load endpoint access policy warning", accessPolicy.Policy)
		logger.Info("loaded endpoint access policy", "path", cfg.EndpointAccessPolicyDir, "tokens", accessPolicy.Policy.Len())
	}
	executor, err := endpointservice.NewExecutor(store, registry, func() {
		if runtime.BeforeInvocation != nil {
			runtime.BeforeInvocation()
		}
	})
	if err == nil {
		// The executor logs a policy refusal where the decision is made, so the
		// command path leaves the same audit trace the read path already leaves.
		// Without this the refusal was durable in the journal and invisible in the
		// log, which made a refused write indistinguishable from an attempt that
		// never happened.
		executor.Logger = logger
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
	// The replace request file is Endpoint-local administrative configuration and
	// the only way to activate a different Provider CLI version for one adapter.
	// An Endpoint that names no file cannot be asked to swap the program it runs,
	// which is the fail-closed default. Activation is reachable only from this
	// local file, never from a Server payload, because a Provider CLI version is an
	// Endpoint deployment detail the Cluster contract deliberately does not model.
	if cfg.ReplaceRequestFile != "" {
		replacer := &endpointservice.Replacer{Registry: registry, Publisher: service}
		replaceFile := &endpointservice.ReplaceFile{
			Path:     cfg.ReplaceRequestFile,
			Replacer: replacer,
			LogConsumed: func(path string) {
				logger.Info("consumed replace request", "path", path)
			},
		}
		stopReplaceReload, replaceErr := replaceFile.WatchReload(ctx, func(result endpointservice.ReplaceFileResult, processErr error) {
			if processErr != nil {
				logger.Error("activate provider cli version", "adapter", result.Result.AdapterID, "request_id", result.RequestID, "error", processErr)
				return
			}
			logger.Info("activated provider cli version",
				"adapter", result.Result.AdapterID,
				"request_id", result.RequestID,
				"previous_version", result.Result.PreviousVersion,
				"effective_version", result.Result.EffectiveVersion,
				"effective_revision", result.Result.EffectiveRevision,
				"in_flight", result.Result.InFlight,
				"reverted", result.Result.Reverted)
		})
		if replaceErr != nil {
			logger.Error("watch replace request file", "error", replaceErr)
			_ = client.Close()
			_ = store.Close()
			os.Exit(1)
		}
		defer stopReplaceReload()
		logger.Info("watching replace request file", "path", cfg.ReplaceRequestFile)
	}
	if err := service.Run(ctx); err != nil {
		logger.Error("endpoint service stopped", "error", err)
	}
	if err := service.Close(); err != nil {
		logger.Error("close endpoint service", "error", err)
	}
}

// logAccessPolicyWarnings emits every load-time warning the policy carries.
//
// The warning is the only signal that a policy file was accepted while granting
// nothing for one of its lines, so it must be emitted at both load sites: the
// startup load and the SIGHUP reload. A reload is the moment an operator expects
// feedback on a file they just edited, so staying silent there would hide the
// mistake exactly when it was introduced.
//
// The event name distinguishes the two sites, and each warning already carries
// its own file path and line number, so one log line identifies the file, the
// line and the reason without the operator correlating two records.
func logAccessPolicyWarnings(logger *slog.Logger, event string, policy *endpointservice.AccessPolicy) {
	if policy == nil {
		return
	}
	for _, warning := range policy.Warnings() {
		logger.Warn(event, "warning", warning)
	}
}
