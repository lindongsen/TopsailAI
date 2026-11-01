package channel

import (
	"context"
	"errors"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

func TestServerRequestOutputRejectsOfflineEndpoint(t *testing.T) {
	server := NewServer(nil)
	response, err := server.RequestOutput(context.Background(), "offline", protocol.OutputSnapshotRequest{})
	if !errors.Is(err, ErrOffline) || response.ErrorCode != "endpoint_offline" {
		t.Fatalf("response=%#v error=%v", response, err)
	}
}

func TestServerFailPendingOutputReportsOnlyMatchingEndpoint(t *testing.T) {
	server := NewServer(nil)
	matching := make(chan Frame, 1)
	other := make(chan Frame, 1)
	server.pendingOutput["matching"] = pendingOutputRequest{endpointID: "e1", response: matching}
	server.pendingOutput["other"] = pendingOutputRequest{endpointID: "e2", response: other}
	server.failPendingOutput("e1", protocol.OutputSnapshotResponse{ErrorCode: "response_too_large"})
	frame := <-matching
	if frame.OutputResponse == nil || frame.OutputResponse.ErrorCode != "response_too_large" {
		t.Fatalf("frame=%#v", frame)
	}
	if _, ok := server.pendingOutput["matching"]; ok {
		t.Fatal("matching pending request was not removed")
	}
	if _, ok := server.pendingOutput["other"]; !ok {
		t.Fatal("unrelated pending request was removed")
	}
}
