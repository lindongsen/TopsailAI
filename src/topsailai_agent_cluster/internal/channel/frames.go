// Package channel provides the authenticated Endpoint channel primitives.
package channel

import (
	"topsailai_agent_cluster/internal/protocol"
	"topsailai_agent_cluster/internal/security"
)

const (
	// ProtocolVersion identifies the channel frame schema.
	ProtocolVersion = "v1"
	// FrameHello starts an Endpoint connection registration.
	FrameHello = "hello"
	// FrameHelloAck confirms the handshake and carries the Endpoint identity.
	FrameHelloAck = "hello_ack"
	// FrameHelloConfirm carries the generation the Server assigned when it
	// installed the connection. The Endpoint attaches only after this frame, so
	// both sides agree on which link is authoritative.
	FrameHelloConfirm = "hello_confirm"
	// FrameHelloAttached confirms that the Endpoint adopted the generation from
	// hello_confirm. The dialing Server waits for it before reporting success, so
	// "successfully established" means both sides adopted the same link rather
	// than only that the Server installed one.
	FrameHelloAttached = "hello_attached"
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
	// FrameInventoryAck acknowledges that Server storage represents the revision.
	FrameInventoryAck = "inventory_ack"
	// FrameCommand carries an immutable command intent.
	FrameCommand = "command"
	// FrameReceipt carries a receipt.
	FrameReceipt = "receipt"
	// FrameReceiptAck acknowledges a persisted receipt.
	FrameReceiptAck = "receipt_ack"
	// FrameReceiptRejected tells the Endpoint that the Server will never apply
	// this receipt. It is a separate frame type from FrameReceiptAck because the
	// two carry different terminal meanings: an acknowledgement says the receipt
	// is stored, while a rejection says it cannot be stored and the Endpoint must
	// decide whether to forget it. Folding them into one frame would force the
	// Endpoint to infer the outcome from an empty field.
	FrameReceiptRejected = "receipt_rejected"
	// FrameOutputRequest requests a bounded provider output snapshot.
	FrameOutputRequest  = "output_request"
	FrameLaunchRequest  = "launch_request"
	FrameLaunchResponse = "launch_response"
	// FrameHistoryRequest requests a bounded provider session-history read.
	FrameHistoryRequest = "history_request"
	// FrameHistoryResponse returns a bounded provider session-history read.
	FrameHistoryResponse = "history_response"
	// FrameMessagesRequest requests a bounded provider conversation read.
	FrameMessagesRequest = "messages_request"
	// FrameMessagesResponse returns a bounded provider conversation read.
	FrameMessagesResponse = "messages_response"
	// FrameMetricsRequest requests one session's current message counts. It is a
	// live observation of a running session, so it is read on demand for the rows
	// an operator is about to see and never collected into the inventory.
	FrameMetricsRequest = "metrics_request"
	// FrameMetricsResponse returns one session's current message counts.
	FrameMetricsResponse = "metrics_response"
	// FrameMetricsBatchRequest requests message counts for a bounded set of
	// sessions on one Endpoint. It exists because the provider cost of a count
	// read is dominated by a fixed scan that does not depend on how many rows are
	// asked for, so one read for a set is far cheaper than one read per row.
	FrameMetricsBatchRequest = "metrics_batch_request"
	// FrameMetricsBatchResponse returns message counts for a bounded set of
	// sessions. A requested session the provider could not measure is absent from
	// the result rather than reported as zero.
	FrameMetricsBatchResponse = "metrics_batch_response"
	// FrameDetailRequest requests one session's provider metadata and runtime
	// document. It is a read-only query, so it carries no generation requirement.
	FrameDetailRequest = "detail_request"
	// FrameDetailResponse returns one session's provider metadata and runtime
	// document.
	FrameDetailResponse = "detail_response"
	// FrameModelCatalogRequest requests a bounded model-catalog read for one
	// session. It is a read-only query, so it carries no generation requirement.
	FrameModelCatalogRequest = "model_catalog_request"
	// FrameModelCatalogResponse returns a bounded model-catalog read.
	FrameModelCatalogResponse = "model_catalog_response"
	// FrameOutputResponse returns a bounded provider output snapshot.
	FrameOutputResponse = "output_response"
	// FrameOutputFollowRequest starts one streaming output follow. It is a
	// separate frame type from FrameOutputRequest because a snapshot has exactly
	// one response while a follow has many.
	FrameOutputFollowRequest = "output_follow_request"
	// FrameOutputChunk carries one bounded batch of followed output lines.
	FrameOutputChunk = "output_chunk"
	// FrameOutputEnd terminates one follow stream. It is always the last frame
	// for its request ID, so a consumer that stops receiving chunks without it
	// treats the stream as interrupted rather than complete.
	FrameOutputEnd = "output_end"
	// FrameOutputFollowCancel tells the Endpoint to stop one follow stream. It is
	// the only frame that carries a consumer's departure, because a follow is the
	// one request whose lifetime is decided by the consumer rather than by the
	// Endpoint: the Server drops its pending entry when the operator stops
	// watching, and without this frame the Endpoint would keep the follow
	// goroutine, its concurrency slot and the provider child alive until the
	// adapter deadline expired. It is sent only when the Endpoint may still be
	// streaming, so a follow that already sent its terminal frame is never
	// cancelled twice.
	FrameOutputFollowCancel = "output_follow_cancel"
	// InitiatorEndpoint marks a connection dialed by the Endpoint.
	InitiatorEndpoint = "endpoint"
	// InitiatorServer marks a connection dialed by the Server.
	InitiatorServer = "server"
)

// Frame is the bounded JSON envelope exchanged over the persistent channel.
type Frame struct {
	LaunchQuery          *protocol.LaunchQuery              `json:"launch_query,omitempty"`
	LaunchOptions        *protocol.LaunchOptions            `json:"launch_options,omitempty"`
	HistoryQuery         *protocol.HistoryQuery             `json:"history_query,omitempty"`
	HistoryResult        *protocol.HistoryResult            `json:"history_result,omitempty"`
	MessagesQuery        *protocol.MessagesQuery            `json:"messages_query,omitempty"`
	MessagesResult       *protocol.MessagesResult           `json:"messages_result,omitempty"`
	MetricsQuery         *protocol.SessionMetricsQuery      `json:"metrics_query,omitempty"`
	MetricsResult        *protocol.SessionMetrics           `json:"metrics_result,omitempty"`
	MetricsBatchQuery    *protocol.SessionMetricsBatchQuery `json:"metrics_batch_query,omitempty"`
	MetricsBatchResult   *protocol.SessionMetricsBatch      `json:"metrics_batch_result,omitempty"`
	DetailQuery          *protocol.SessionDetailQuery       `json:"detail_query,omitempty"`
	DetailResult         *protocol.SessionDetail            `json:"detail_result,omitempty"`
	ModelCatalogQuery    *protocol.ModelCatalogQuery        `json:"model_catalog_query,omitempty"`
	ModelCatalog         *protocol.ModelCatalog             `json:"model_catalog,omitempty"`
	Type                 string                             `json:"type"`
	ProtocolVersion      string                             `json:"protocol_version"`
	FrameID              string                             `json:"frame_id,omitempty"`
	ConnectionGeneration string                             `json:"connection_generation"`
	Initiator            string                             `json:"initiator,omitempty"`
	EndpointID           string                             `json:"endpoint_id,omitempty"`
	InstanceID           string                             `json:"instance_id,omitempty"`
	// ServerIdentity names the Server database that admitted this connection's
	// commands. The Endpoint compares it across reconnects to tell "the same
	// Server restarted" from "a different Server now manages me", because only
	// the second case makes recorded receipts permanently inapplicable.
	//
	// It is the database identity rather than a process identity: a restarted
	// Server still holds the commands it admitted, so its receipts must still be
	// re-sent.
	ServerIdentity string `json:"server_identity,omitempty"`
	Hostname       string `json:"hostname,omitempty"`
	RequestID      string `json:"request_id,omitempty"`
	Reason         string `json:"reason,omitempty"`
	// ReceiptRejection carries the closed reason vocabulary for
	// FrameReceiptRejected. It is typed rather than folded into Reason so an
	// unrecognised value stays distinguishable from an absent one: the Endpoint
	// must keep the receipt pending when it cannot interpret the reason.
	ReceiptRejection    protocol.ReceiptRejection        `json:"receipt_rejection,omitempty"`
	SnapshotRevision    int64                            `json:"snapshot_revision,omitempty"`
	Payload             any                              `json:"payload,omitempty"`
	Intent              *protocol.ImmutableIntent        `json:"intent,omitempty"`
	Receipt             *protocol.ExecutionReceipt       `json:"receipt,omitempty"`
	OutputRequest       *protocol.OutputSnapshotRequest  `json:"output_request,omitempty"`
	OutputResponse      *protocol.OutputSnapshotResponse `json:"output_response,omitempty"`
	OutputFollowRequest *protocol.OutputFollowRequest    `json:"output_follow_request,omitempty"`
	OutputChunk         *protocol.OutputChunk            `json:"output_chunk,omitempty"`
	OutputEnd           *protocol.OutputEnd              `json:"output_end,omitempty"`
	// EndpointCredential is the caller's Endpoint credential, forwarded verbatim
	// by the Server and verified by the Endpoint policy check.
	//
	// It lives on the envelope rather than inside each request structure for
	// three reasons. It is a transport credential, not part of the request
	// meaning, so it must not enter ImmutableIntent.CanonicalHash: a credential
	// rotation would otherwise change the deduplication identity of an unchanged
	// command. It must not enter the command journal, which stores the intent, so
	// keeping it out of the intent keeps the secret out of the audit trail. And
	// one field covers every frame type, so a new request type cannot be added
	// without a place to carry the credential.
	//
	// It is a struct rather than a string because the Endpoint must be able to
	// tell a bearer token from an HMAC signature. A single string field would
	// force the Endpoint to guess which form it received, and a guess is how a
	// caller downgrades a stronger mode by sending the weaker syntax.
	EndpointCredential *security.EndpointCredential `json:"endpoint_credential,omitempty"`
	// EndpointRequestDigest is the digest of the operator request that carried
	// EndpointCredential, computed by the Server from the request as it arrived.
	//
	// It travels on the envelope because the Endpoint never sees the HTTP
	// request: the Server is the only party that can describe what was actually
	// received, and the Endpoint is the only party that verifies the signature.
	// Without it the signature would cover the operation and the machine but not
	// the request, so a captured signature could be replayed against a different
	// target on the same machine.
	//
	// It is empty for a bearer credential, which has no signature to bind.
	EndpointRequestDigest string `json:"endpoint_request_digest,omitempty"`
}
