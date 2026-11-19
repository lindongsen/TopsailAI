package protocol

import (
	"fmt"
	"strings"
)

// FileTransportVersion names one representation used to carry file content on
// the Node-to-Server channel.
type FileTransportVersion string

const (
	// FileTransportBinaryV1 carries file bytes outside JSON without compression.
	FileTransportBinaryV1 FileTransportVersion = "binary-v1"
)

// FileTransportIncompatibilityError reports that two valid capability lists
// have no version in common. Version names are public protocol identifiers, so
// the error is safe to show as upgrade guidance.
type FileTransportIncompatibilityError struct {
	Server []FileTransportVersion
	Node   []FileTransportVersion
}

// Error implements error with the public versions each peer supports.
func (e *FileTransportIncompatibilityError) Error() string {
	return fmt.Sprintf(
		"no common file transport version (server: %s; node: %s)",
		formatFileTransportVersions(e.Server),
		formatFileTransportVersions(e.Node),
	)
}

// NegotiateFileTransport selects the first Server-preferred version also
// offered by the Node. It refuses malformed lists rather than normalizing them,
// because capability negotiation must have one unambiguous input on both peers.
func NegotiateFileTransport(serverPreferred, nodeOffered []FileTransportVersion) (FileTransportVersion, error) {
	if err := validateFileTransportVersions("server", serverPreferred); err != nil {
		return "", err
	}
	if err := validateFileTransportVersions("node", nodeOffered); err != nil {
		return "", err
	}

	offered := make(map[FileTransportVersion]struct{}, len(nodeOffered))
	for _, version := range nodeOffered {
		offered[version] = struct{}{}
	}
	for _, version := range serverPreferred {
		if _, ok := offered[version]; ok {
			return version, nil
		}
	}

	return "", &FileTransportIncompatibilityError{
		Server: append([]FileTransportVersion(nil), serverPreferred...),
		Node:   append([]FileTransportVersion(nil), nodeOffered...),
	}
}

// validateFileTransportVersions refuses empty names and duplicate entries.
func validateFileTransportVersions(peer string, versions []FileTransportVersion) error {
	seen := make(map[FileTransportVersion]struct{}, len(versions))
	for index, version := range versions {
		if version == "" {
			return fmt.Errorf("%s file transport version %d is empty", peer, index)
		}
		if _, ok := seen[version]; ok {
			return fmt.Errorf("%s file transport version %q is duplicated", peer, version)
		}
		seen[version] = struct{}{}
	}
	return nil
}

// formatFileTransportVersions formats public version names for an error.
func formatFileTransportVersions(versions []FileTransportVersion) string {
	if len(versions) == 0 {
		return "none"
	}
	formatted := make([]string, len(versions))
	for index, version := range versions {
		formatted[index] = string(version)
	}
	return strings.Join(formatted, ",")
}
