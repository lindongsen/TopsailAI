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

// RejectSender tells the Endpoint that a receipt can never be applied, together
// with the closed reason it needs in order to decide whether to forget it.
type RejectSender func(context.Context, string, protocol.ReceiptRejection) error

// PersistReceiptAndAck records a receipt before acknowledging its transport frame.
//
// A receipt the Server can never apply is reported to the Endpoint as a
// rejection rather than only logged. Without that report the Endpoint keeps the
// receipt pending and re-sends it on every reconnect, because it reloads the
// pending set from its journal. After a re-home every receipt from the previous
// Server is unknown here, so the omission would turn one re-home into a
// permanent resend loop.
//
// A rejection is not an acknowledgement: the receipt was not stored. The
// Endpoint decides from the reason whether it may forget the receipt, and an
// integrity conflict is deliberately not forgettable.
func PersistReceiptAndAck(ctx context.Context, store *serverstorage.Store, receipt protocol.ExecutionReceipt, peer channel.Peer, now time.Time, ack AckSender, reject RejectSender) error {
	if store == nil || ack == nil {
		return errors.New("receipt store and acknowledgement function are required")
	}
	if err := store.ApplyReceipt(ctx, receipt, now.UnixMilli()); err != nil {
		var rejection *serverstorage.ReceiptRejectionError
		if errors.As(err, &rejection) && reject != nil {
			if rejectErr := reject(ctx, peer.EndpointID, rejection.Reason); rejectErr != nil {
				return errors.Join(err, rejectErr)
			}
		}
		return err
	}
	return ack(ctx, peer.EndpointID)
}
