package protocol

import (
	"errors"
	"strings"
	"testing"
)

// TestNegotiateFileTransportUsesServerPreference checks that the Server decides
// preference while the Node decides which versions are available.
func TestNegotiateFileTransportUsesServerPreference(t *testing.T) {
	selected, err := NegotiateFileTransport(
		[]FileTransportVersion{"binary-v2", FileTransportBinaryV1},
		[]FileTransportVersion{FileTransportBinaryV1, "binary-v2"},
	)
	if err != nil {
		t.Fatalf("negotiate file transport: %v", err)
	}
	if selected != "binary-v2" {
		t.Fatalf("selected = %q, want %q", selected, FileTransportVersion("binary-v2"))
	}
}

// TestNegotiateFileTransportIgnoresNodeOrder checks that Node advertisement
// order cannot change the Server's deterministic choice.
func TestNegotiateFileTransportIgnoresNodeOrder(t *testing.T) {
	server := []FileTransportVersion{"binary-v2", FileTransportBinaryV1}

	first, err := NegotiateFileTransport(server, []FileTransportVersion{FileTransportBinaryV1, "binary-v2"})
	if err != nil {
		t.Fatalf("negotiate first offer: %v", err)
	}
	second, err := NegotiateFileTransport(server, []FileTransportVersion{"binary-v2", FileTransportBinaryV1})
	if err != nil {
		t.Fatalf("negotiate second offer: %v", err)
	}
	if first != second {
		t.Fatalf("selection changed with node order: first %q, second %q", first, second)
	}
}

// TestNegotiateFileTransportRejectsMalformedLists checks that capability lists
// are refused rather than repaired, so both peers reason about the same input.
func TestNegotiateFileTransportRejectsMalformedLists(t *testing.T) {
	tests := []struct {
		name   string
		server []FileTransportVersion
		node   []FileTransportVersion
		want   string
	}{
		{
			name:   "empty server version",
			server: []FileTransportVersion{""},
			node:   []FileTransportVersion{FileTransportBinaryV1},
			want:   "server file transport version 0 is empty",
		},
		{
			name:   "duplicate server version",
			server: []FileTransportVersion{FileTransportBinaryV1, FileTransportBinaryV1},
			node:   []FileTransportVersion{FileTransportBinaryV1},
			want:   `server file transport version "binary-v1" is duplicated`,
		},
		{
			name:   "empty node version",
			server: []FileTransportVersion{FileTransportBinaryV1},
			node:   []FileTransportVersion{""},
			want:   "node file transport version 0 is empty",
		},
		{
			name:   "duplicate node version",
			server: []FileTransportVersion{FileTransportBinaryV1},
			node:   []FileTransportVersion{FileTransportBinaryV1, FileTransportBinaryV1},
			want:   `node file transport version "binary-v1" is duplicated`,
		},
	}

	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			selected, err := NegotiateFileTransport(test.server, test.node)
			if err == nil {
				t.Fatalf("selected %q without an error", selected)
			}
			if err.Error() != test.want {
				t.Fatalf("error = %q, want %q", err, test.want)
			}
		})
	}
}

// TestNegotiateFileTransportReportsTypedIncompatibility checks that disjoint
// valid offers produce upgrade guidance that callers can classify.
func TestNegotiateFileTransportReportsTypedIncompatibility(t *testing.T) {
	server := []FileTransportVersion{FileTransportBinaryV1}
	node := []FileTransportVersion{"json-v1"}

	selected, err := NegotiateFileTransport(server, node)
	if err == nil {
		t.Fatalf("selected %q without an incompatibility error", selected)
	}

	var incompatibility *FileTransportIncompatibilityError
	if !errors.As(err, &incompatibility) {
		t.Fatalf("error type = %T, want *FileTransportIncompatibilityError", err)
	}
	if !strings.Contains(err.Error(), "server: binary-v1; node: json-v1") {
		t.Fatalf("error = %q, want public version guidance", err)
	}

	server[0] = "changed-server"
	node[0] = "changed-node"
	if incompatibility.Server[0] != FileTransportBinaryV1 {
		t.Fatalf("stored server version = %q, want an input copy", incompatibility.Server[0])
	}
	if incompatibility.Node[0] != "json-v1" {
		t.Fatalf("stored node version = %q, want an input copy", incompatibility.Node[0])
	}
}

// TestNegotiateFileTransportReportsEmptyOffers checks that absent support is an
// explicit incompatibility instead of an implicit legacy fallback.
func TestNegotiateFileTransportReportsEmptyOffers(t *testing.T) {
	_, err := NegotiateFileTransport(nil, nil)
	if err == nil {
		t.Fatal("expected empty offers to be incompatible")
	}
	if err.Error() != "no common file transport version (server: none; node: none)" {
		t.Fatalf("error = %q", err)
	}
}
