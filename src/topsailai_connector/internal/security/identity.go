package security

import (
	"crypto/rand"
	"encoding/base32"
	"errors"
	"fmt"
	"strings"
)

// NodeIDPrefix is the fixed prefix of every node identifier. The prefix makes a
// node identifier recognisable in a log or a URL, so a value that is an address
// cannot be mistaken for a value that is a credential.
const NodeIDPrefix = "node_"

// nodeIDRandomBytes is the entropy behind a node identifier. 16 bytes is 128
// bits, which is enough that two Nodes started independently never collide and a
// guessed identifier is not a way to find a Node.
const nodeIDRandomBytes = 16

// nodeIDEncoding is unpadded base32: lowercase letters and digits only, so an
// identifier survives a URL, a shell argument and a Windows file name without
// escaping.
var nodeIDEncoding = base32.StdEncoding.WithPadding(base32.NoPadding)

// NewNodeID generates a fresh node identifier from the system random source.
//
// The Node generates its own identifier rather than receiving one from the Server,
// because an identity authority can also deny identity: a Node that names itself
// works without the Server being reachable, and the Server never becomes a
// component whose absence prevents a Node from starting.
//
// The identifier is an address, not a credential. The credential that authorizes an
// operation is a separate value held in the Node's credential file, so knowing an
// identifier grants nothing.
func NewNodeID() (string, error) {
	buffer := make([]byte, nodeIDRandomBytes)
	if _, err := rand.Read(buffer); err != nil {
		return "", fmt.Errorf("generate node id: %w", err)
	}
	return NodeIDPrefix + strings.ToLower(nodeIDEncoding.EncodeToString(buffer)), nil
}

// nodeIDBodyLength is the number of characters the generator emits after the
// prefix. It is derived from nodeIDRandomBytes rather than written as a literal,
// so a change to the entropy cannot leave the validator checking a length the
// generator no longer produces.
const nodeIDBodyLength = (nodeIDRandomBytes*8 + 4) / 5

// ValidateNodeID checks that an identifier has the fixed prefix, the exact
// length the generator produces and only alphabet characters. A length check is
// not a security control, but it turns a truncated identifier into a startup
// failure instead of a Node that can never be addressed.
func ValidateNodeID(id string) error {
	if id == "" {
		return errors.New("node id is empty")
	}
	if strings.TrimSpace(id) != id {
		return fmt.Errorf("node id %q has leading or trailing whitespace", id)
	}
	if !strings.HasPrefix(id, NodeIDPrefix) {
		return fmt.Errorf("node id %q does not start with %q", id, NodeIDPrefix)
	}
	body := id[len(NodeIDPrefix):]
	if body == "" {
		return fmt.Errorf("node id %q has no body after the prefix", id)
	}
	if len(body) != nodeIDBodyLength {
		return fmt.Errorf("node id %q has a %d character body, want %d", id, len(body), nodeIDBodyLength)
	}
	for _, character := range body {
		if !isNodeIDCharacter(character) {
			return fmt.Errorf("node id %q contains %q, which is not a lowercase letter or digit", id, character)
		}
	}
	return nil
}

// isNodeIDCharacter reports whether a character belongs to the unpadded base32
// alphabet used for identifiers.
func isNodeIDCharacter(character rune) bool {
	switch {
	case character >= 'a' && character <= 'z':
		return true
	case character >= '0' && character <= '9':
		return true
	default:
		return false
	}
}
