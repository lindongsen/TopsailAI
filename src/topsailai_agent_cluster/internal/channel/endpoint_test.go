package channel

import (
	"context"
	"errors"
	"testing"
)

func TestEndpointClientRejectsInvalidHeartbeatAndOfflineOperations(t *testing.T) {
	client := &EndpointClient{}
	if err := client.RunHeartbeat(context.Background(), 0); err == nil {
		t.Fatal("zero heartbeat interval must fail")
	}
	if err := client.SendHeartbeat(context.Background()); !errors.Is(err, ErrOffline) {
		t.Fatalf("heartbeat error=%v", err)
	}
	if _, err := client.Read(context.Background()); !errors.Is(err, ErrOffline) {
		t.Fatalf("read error=%v", err)
	}
	if err := client.SendFrame(context.Background(), Frame{}); !errors.Is(err, ErrOffline) {
		t.Fatalf("send error=%v", err)
	}
	if err := client.Reconnect(context.Background()); err == nil {
		t.Fatal("reconnect without address must fail")
	}
}
