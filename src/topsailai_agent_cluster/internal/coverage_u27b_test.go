package internal_test

import (
	"context"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
	"topsailai_agent_cluster/internal/server"
)

func TestChannelTransportRejectsMissingChannel(t *testing.T) {
	if err := (server.ChannelTransport{}).Send(context.Background(), protocol.TransportEnvelope{}); err == nil {
		t.Fatal("missing channel was accepted")
	}
}
