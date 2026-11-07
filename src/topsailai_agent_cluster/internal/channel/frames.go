// Package channel provides the authenticated Endpoint channel primitives.
package channel

import "topsailai_agent_cluster/internal/protocol"

const (
	// ProtocolVersion identifies the channel frame schema.
	ProtocolVersion = "v1"
	// FrameHello starts an Endpoint connection registration.
	FrameHello = "hello"
	// FrameHelloAck confirms the active connection generation.
	FrameHelloAck = "hello_ack"
	// FrameHelloRejected explains an authenticated handshake rejection before closure.
	FrameHelloRejected = "hello_rejected"
	// FrameHeartbeat is an application-level liveness frame.
	FrameHeartbeat = "heartbeat"
	// FrameHeartbeatAck acknowledges liveness.
	FrameHeartbeatAck = "heartbeat_ack"
	// FrameInventory carries a complete Endpoint inventory report.
	FrameInventory = "inventory"
	// FrameInventoryRefresh requests a fresh Endpoint collection.
	FrameInventoryRefresh = "inventory_refresh"
	// FrameCommand carries an immutable command intent.
	FrameCommand = "command"
	// FrameReceipt carries a receipt.
	FrameReceipt = "receipt"
	// FrameReceiptAck acknowledges a persisted receipt.
	FrameReceiptAck = "receipt_ack"
	// FrameOutputRequest requests a bounded provider output snapshot.
	FrameOutputRequest  = "output_request"
	FrameLaunchRequest  = "launch_request"
	FrameLaunchResponse = "launch_response"
	// FrameOutputResponse returns a bounded provider output snapshot.
	FrameOutputResponse = "output_response"
	// InitiatorEndpoint marks a connection dialed by the Endpoint.
	InitiatorEndpoint = "endpoint"
	// InitiatorServer marks a connection dialed by the Server.
	InitiatorServer = "server"
)

// Frame is the bounded JSON envelope exchanged over the persistent channel.
type Frame struct {
	LaunchQuery          *protocol.LaunchQuery            `json:"launch_query,omitempty"`
	LaunchOptions        *protocol.LaunchOptions          `json:"launch_options,omitempty"`
	Type                 string                           `json:"type"`
	ProtocolVersion      string                           `json:"protocol_version"`
	FrameID              string                           `json:"frame_id,omitempty"`
	ConnectionGeneration string                           `json:"connection_generation"`
	Initiator            string                           `json:"initiator,omitempty"`
	EndpointID           string                           `json:"endpoint_id,omitempty"`
	InstanceID           string                           `json:"instance_id,omitempty"`
	Hostname             string                           `json:"hostname,omitempty"`
	RequestID            string                           `json:"request_id,omitempty"`
	Reason               string                           `json:"reason,omitempty"`
	SnapshotRevision     int64                            `json:"snapshot_revision,omitempty"`
	Payload              any                              `json:"payload,omitempty"`
	Intent               *protocol.ImmutableIntent        `json:"intent,omitempty"`
	Receipt              *protocol.ExecutionReceipt       `json:"receipt,omitempty"`
	OutputRequest        *protocol.OutputSnapshotRequest  `json:"output_request,omitempty"`
	OutputResponse       *protocol.OutputSnapshotResponse `json:"output_response,omitempty"`
}
