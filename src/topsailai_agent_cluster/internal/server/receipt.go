package server

import (
	"context"
	"errors"
	"time"

	"topsailai_agent_cluster/internal/channel"
	"topsailai_agent_cluster/internal/protocol"
	serverstorage "topsailai_agent_cluster/internal/storage/server"
)

// AckSender sends an acknowledgement for a persisted receipt.
type AckSender func(context.Context, string) error

// PersistReceiptAndAck records a receipt before acknowledging its transport frame.
func PersistReceiptAndAck(ctx context.Context, store *serverstorage.Store, receipt protocol.ExecutionReceipt, peer channel.Peer, now time.Time, ack AckSender) error {
	if store == nil || ack == nil {
		return errors.New("receipt store and acknowledgement function are required")
	}
	if err := store.ApplyReceipt(ctx, receipt, now.UnixMilli()); err != nil {
		return err
	}
	return ack(ctx, peer.EndpointID)
}
