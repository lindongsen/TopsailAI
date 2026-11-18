package main

import (
	"context"
	"encoding/json"
	"log/slog"

	"topsailai_agent_cluster/internal/channel"
	"topsailai_agent_cluster/internal/protocol"
)

// admissionNotifier publishes the endpoint_admitted receipt and runs the
// test-only hold for that phase.
//
// The collaborators are function values rather than concrete types because the
// runtime hooks have two build-tag variants and the channel client is a concrete
// struct. Injecting the behaviour keeps this decision testable without either
// variant leaking into the test.
type admissionNotifier struct {
	send   func(context.Context, channel.Frame) error
	hold   func(string) error
	wait   func(*slog.Logger, string) error
	logger *slog.Logger
}

// notify tells the Server that this command was admitted, then runs the hold.
//
// A transport failure on the admission frame is logged and tolerated. The frame
// is a courtesy, not a precondition: the provider call needs no channel, and the
// final receipt is retried on reconnect. Aborting here made a temporary
// connectivity state permanent, because the executor returned an empty receipt,
// executeFrame dropped it for having no command ID, and the Server then converged
// a command that provably never ran to unconfirmed/unknown.
//
// A hold failure is still returned. The hold is a test synchronisation point, so
// a hold that cannot be reached means the test's premise is broken and the
// command must not proceed as if it had been observed.
func (n admissionNotifier) notify(ctx context.Context, intent protocol.ImmutableIntent, requestHash string) error {
	receipt := protocol.ExecutionReceipt{
		CommandID:        intent.CommandID,
		RequestHash:      requestHash,
		Phase:            protocol.PhaseInvocationStarted,
		DeliveryBoundary: protocol.DeliveryNotStarted,
		EffectCertainty:  protocol.EffectUnknown,
		Outcome:          "endpoint_admitted",
	}
	data, err := json.Marshal(receipt)
	if err != nil {
		return err
	}
	if n.send != nil {
		frame := channel.Frame{
			Type:            channel.FrameReceipt,
			ProtocolVersion: channel.ProtocolVersion,
			FrameID:         intent.CommandID,
			RequestID:       intent.CommandID,
			Receipt:         &receipt,
			Payload:         json.RawMessage(data),
		}
		if sendErr := n.send(ctx, frame); sendErr != nil {
			// WARN rather than ERROR: an offline channel is a connectivity state,
			// not a failure of this operation, which is the distinction
			// logTransportError already makes on the Endpoint service.
			if n.logger != nil {
				n.logger.Warn("publish endpoint admission", "command_id", intent.CommandID, "error", sendErr)
			}
		}
	}
	if n.hold != nil {
		if holdErr := n.hold("endpoint_admitted"); holdErr != nil {
			return holdErr
		}
	}
	if n.wait != nil {
		return n.wait(n.logger, "endpoint_admitted")
	}
	return nil
}
