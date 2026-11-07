package main

import (
	"context"
	"crypto/tls"
	"log/slog"
	"time"

	"topsailai_agent_cluster/internal/channel"
	"topsailai_agent_cluster/internal/config"
	"topsailai_agent_cluster/internal/security"
)

// dialRetryInterval bounds how often the Server retries one unreachable
// Endpoint. It is a fixed interval rather than an exponential backoff because a
// fleet has few Endpoints and a steady retry keeps recovery time predictable.
const dialRetryInterval = 2 * time.Second

// runEndpointDialer dials every configured Endpoint and keeps retrying while it
// is offline. It is used in the server-initiated direction, where the Server
// cannot wait for the Endpoint to connect because the network path only works
// the other way round.
//
// Each Endpoint is dialed by its own goroutine so one unreachable machine cannot
// delay the others, and the loop stops when the context is cancelled.
func runEndpointDialer(ctx context.Context, logger *slog.Logger, channelService *channel.Server, cfg config.Config) {
	for endpointID, address := range cfg.EndpointDialAddresses {
		endpointID, address := endpointID, address
		go func() {
			// The Server dials the Endpoint, so it must verify the Endpoint
			// certificate. The expected name is the Endpoint identity, which is
			// what the Endpoint certificate carries.
			dialTLS, err := security.LoadMTLSConfig(security.MTLSConfig{CAFile: cfg.TLSCAFile, CertificateFile: cfg.TLSCertificateFile, KeyFile: cfg.TLSKeyFile, RevokedSerialsFile: cfg.TLSRevokedSerialsFile, ServerName: endpointID}, false)
			if err != nil {
				logger.Error("load endpoint dial TLS configuration", "endpoint_id", endpointID, "error", err)
				return
			}
			dialLoop(ctx, logger, channelService, endpointID, address, dialTLS)
		}()
	}
}

// dialLoop keeps one Endpoint connected for as long as the context lives.
func dialLoop(ctx context.Context, logger *slog.Logger, channelService *channel.Server, endpointID, address string, dialTLS *tls.Config) {
	ticker := time.NewTicker(dialRetryInterval)
	defer ticker.Stop()
	for {
		if ctx.Err() != nil {
			return
		}
		if !channelService.IsOnline(endpointID, time.Now()) {
			if _, err := channelService.DialEndpoint(ctx, endpointID, address, dialTLS); err != nil {
				if ctx.Err() != nil {
					return
				}
				logger.Warn("dial endpoint channel; retrying", "endpoint_id", endpointID, "address", address, "error", err)
			} else {
				logger.Info("dialed endpoint channel", "endpoint_id", endpointID, "address", address)
			}
		}
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
		}
	}
}
