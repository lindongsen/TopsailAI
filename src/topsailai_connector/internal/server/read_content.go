package server

import (
	"encoding/json"
	"fmt"

	"topsailai_connector/internal/protocol"
)

// readMetadata is the payload a Node sends for a successful `file.read` on the
// content transport.
//
// It is declared here rather than imported from the Node because the Server must
// not depend on the Node's package: the two binaries are separate, and a shared
// struct would make one binary's build depend on the other's internals. The field
// names are the wire contract, and they are the same names the JSON transport
// uses, so a caller reading either shape finds the same keys.
type readMetadata struct {
	Size      int64 `json:"size"`
	Truncated bool  `json:"truncated"`
}

// readResult is the payload of a successful `file.read` as the CLI receives it.
//
// The content is a byte slice, so the JSON encoder emits base64. That is the
// documented shape in docs/API.md and it does not change with the transport: the
// transport decides how the bytes travel between the Node and the Server, not what
// the caller sees.
type readResult struct {
	Content   []byte `json:"content"`
	Size      int64  `json:"size"`
	Truncated bool   `json:"truncated"`
}

// mergeReadContent rebuilds the documented read shape from metadata and bytes.
//
// The metadata is decoded strictly enough to catch a mismatch: a response that
// does not parse, or whose size disagrees with the bytes that arrived, is an error
// rather than a silently truncated file. A caller that receives a short file with
// a correct-looking size has no way to notice, so the disagreement is refused here
// where both halves are still available.
func mergeReadContent(metadata []byte, content []byte) ([]byte, error) {
	var meta readMetadata
	if err := json.Unmarshal(metadata, &meta); err != nil {
		return nil, fmt.Errorf("decode read metadata: %w", err)
	}
	if meta.Size != int64(len(content)) {
		return nil, fmt.Errorf("read metadata reports %d bytes but %d arrived", meta.Size, len(content))
	}
	return json.Marshal(readResult{
		Content:   content,
		Size:      meta.Size,
		Truncated: meta.Truncated,
	})
}

// serverPreferredTransports is the Server's preference order for file content.
//
// The list is ordered most-preferred first, and it is the Server's list because
// the Server is the party that must decode what arrives. A Node that offers
// nothing keeps the original JSON transport, which is why an empty list is not an
// incompatibility: an older Node has no capability list at all, and refusing it
// would break every deployment that upgrades the Server first.
var serverPreferredTransports = []protocol.FileTransportVersion{
	protocol.FileTransportBinaryV1,
}

// negotiateChannelTransport selects the file content transport for one channel.
//
// An empty Node list means the Node predates capability negotiation, so the
// channel uses the original JSON transport and the handshake carries no version.
// A non-empty list that shares no version with the Server is refused rather than
// silently downgraded, because a downgrade would hide an upgrade mistake behind a
// working-but-slow channel.
func negotiateChannelTransport(nodeOffered []protocol.FileTransportVersion) (protocol.FileTransportVersion, error) {
	if len(nodeOffered) == 0 {
		return "", nil
	}
	return protocol.NegotiateFileTransport(serverPreferredTransports, nodeOffered)
}

// transportName renders a negotiated transport for a log line.
//
// An empty version is the original JSON transport, which is named rather than
// printed as an empty string so a log reader can tell "legacy" from "missing".
func transportName(transport protocol.FileTransportVersion) string {
	if transport == "" {
		return "json"
	}
	return string(transport)
}
