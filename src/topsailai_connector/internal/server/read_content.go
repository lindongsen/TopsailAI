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

// validateReadContent checks that the metadata agrees with the bytes that arrived.
//
// The check exists because a caller that receives fewer bytes than the metadata
// promised has no way to notice: the file looks complete and is short. The
// disagreement is refused where both halves are still available, which is here.
//
// It is separate from mergeReadContent so the streaming path can perform the same
// check without building the merged JSON. A check that only existed inside the
// merge would be a check the streaming path could not reach, and a streaming path
// without it would publish a short file.
func validateReadContent(metadata []byte, content []byte) (readMetadata, error) {
	var meta readMetadata
	if err := json.Unmarshal(metadata, &meta); err != nil {
		return readMetadata{}, fmt.Errorf("decode read metadata: %w", err)
	}
	if meta.Size != int64(len(content)) {
		return readMetadata{}, fmt.Errorf("read metadata reports %d bytes but %d arrived", meta.Size, len(content))
	}
	return meta, nil
}

// mergeReadContent rebuilds the documented read shape from metadata and bytes.
//
// This is the legacy caller-facing shape: one JSON object with a base64 content
// field. It is built only for a caller that did not opt in to the raw stream, so
// the base64 cost is paid by the caller that asked for the old contract and not by
// the one that asked for the new one.
func mergeReadContent(metadata []byte, content []byte) ([]byte, error) {
	meta, err := validateReadContent(metadata, content)
	if err != nil {
		return nil, err
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
