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

// nodeTokenRandomBytes is the entropy behind a node token. 32 bytes is 256 bits,
// which is the size a shared secret needs when it never expires.
const nodeTokenRandomBytes = 32

// nodeIDEncoding is unpadded base32: lowercase letters and digits only, so an
// identifier survives a URL, a shell argument and a Windows file name without
// escaping.
var nodeIDEncoding = base32.StdEncoding.WithPadding(base32.NoPadding)

// ErrMalformedPair reports a node-id.node-token pair that could not be split.
// Every malformed form produces this one error, because a caller that can tell
// "no dot" from "empty token" learns the shape of a valid pair.
var ErrMalformedPair = errors.New("malformed node-id.node-token pair")

// NodeIdentity is the pair a Node generates for itself: a public identifier and
// the secret that authorizes operations on it.
//
// The two halves have different jobs and must be treated differently from the
// moment they are received. The identifier is an address that appears in URLs,
// in audit records and in the Server's routing table. The token is a credential
// that must never be logged. Keeping them in one string is a copying
// convenience, not a claim that they are the same kind of value.
type NodeIdentity struct {
	ID    string
	Token Secret
}

// NewNodeIdentity generates a fresh identity from the system random source.
//
// The Node generates its own identity rather than receiving one from the Server,
// because an identity authority can also deny identity: a Node that names itself
// works without the Server being reachable, and the Server never becomes a
// component whose absence prevents a Node from starting.
func NewNodeIdentity() (NodeIdentity, error) {
	id, err := randomNodeID()
	if err != nil {
		return NodeIdentity{}, err
	}
	token, err := randomNodeToken()
	if err != nil {
		return NodeIdentity{}, err
	}
	return NodeIdentity{ID: id, Token: token}, nil
}

// NewNodeToken generates a fresh token while keeping an existing identifier,
// which is what a regeneration that must not disturb the CLI's routing target
// needs. The identifier is validated first, so a regeneration cannot preserve a
// name that was never valid.
func NewNodeToken(id string) (NodeIdentity, error) {
	if err := ValidateNodeID(id); err != nil {
		return NodeIdentity{}, err
	}
	token, err := randomNodeToken()
	if err != nil {
		return NodeIdentity{}, err
	}
	return NodeIdentity{ID: id, Token: token}, nil
}

// randomNodeID builds one identifier from the random source.
func randomNodeID() (string, error) {
	buffer := make([]byte, nodeIDRandomBytes)
	if _, err := rand.Read(buffer); err != nil {
		return "", fmt.Errorf("generate node id: %w", err)
	}
	return NodeIDPrefix + strings.ToLower(nodeIDEncoding.EncodeToString(buffer)), nil
}

// randomNodeToken builds one token from the random source.
func randomNodeToken() (Secret, error) {
	buffer := make([]byte, nodeTokenRandomBytes)
	if _, err := rand.Read(buffer); err != nil {
		return "", fmt.Errorf("generate node token: %w", err)
	}
	return Secret(strings.ToLower(nodeIDEncoding.EncodeToString(buffer))), nil
}

// String renders the pair in the form the operator copies: identifier, one dot,
// token. It is the only method that returns the token, so a caller that wants
// the token has to ask for the whole pair and split it deliberately.
func (n NodeIdentity) String() string {
	return n.ID + "." + string(n.Token)
}

// Redacted renders the pair with the token replaced, so an identity can appear
// in a log or an error message. The identifier is kept because it is an address,
// not a credential.
func (n NodeIdentity) Redacted() string {
	return n.ID + "." + n.Token.Redacted()
}

// ParseNodeIdentity splits a node-id.node-token pair.
//
// Every rule here is a refusal rather than a repair, because a repaired pair is
// a pair the operator did not write:
//
//   - The split is on the first dot. Splitting on the last dot would silently
//     move the boundary if a token ever contained one, and the two halves would
//     then be different values than the ones that were generated.
//   - A pair with no dot is refused, because a lone identifier is not a
//     credential and a lone token is not an address.
//   - An empty half is refused, because an empty token would compare equal to an
//     empty configured secret if that check were ever skipped.
//   - A second dot in the token half is refused, because the token alphabet has
//     no dot, so a dot there means the value was mangled in transit.
//   - Whitespace is refused rather than trimmed. Trimming would hide a
//     copy-paste error that would otherwise surface as a confusing auth failure.
func ParseNodeIdentity(pair string) (NodeIdentity, error) {
	if pair == "" {
		return NodeIdentity{}, fmt.Errorf("%w: value is empty", ErrMalformedPair)
	}
	if strings.TrimSpace(pair) != pair {
		return NodeIdentity{}, fmt.Errorf("%w: value has leading or trailing whitespace", ErrMalformedPair)
	}
	index := strings.Index(pair, ".")
	if index < 0 {
		return NodeIdentity{}, fmt.Errorf("%w: no dot separating the identifier from the token", ErrMalformedPair)
	}
	id := pair[:index]
	token := pair[index+1:]
	if id == "" {
		return NodeIdentity{}, fmt.Errorf("%w: identifier half is empty", ErrMalformedPair)
	}
	if token == "" {
		return NodeIdentity{}, fmt.Errorf("%w: token half is empty", ErrMalformedPair)
	}
	if strings.Contains(token, ".") {
		return NodeIdentity{}, fmt.Errorf("%w: token half contains a second dot", ErrMalformedPair)
	}
	if err := ValidateNodeID(id); err != nil {
		return NodeIdentity{}, fmt.Errorf("%w: %v", ErrMalformedPair, err)
	}
	if err := ValidateNodeToken(Secret(token)); err != nil {
		return NodeIdentity{}, fmt.Errorf("%w: %v", ErrMalformedPair, err)
	}
	return NodeIdentity{ID: id, Token: Secret(token)}, nil
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

// ValidateNodeToken checks that a token is non-empty and uses the generated
// alphabet. It does not check the length, because a token that was generated by
// an older build with a different size must still be comparable; the length is
// the generator's business, not the parser's.
func ValidateNodeToken(token Secret) error {
	if token == "" {
		return errors.New("node token is empty")
	}
	for _, character := range string(token) {
		if !isNodeIDCharacter(character) {
			return fmt.Errorf("node token contains %q, which is not a lowercase letter or digit", character)
		}
	}
	return nil
}

// isNodeIDCharacter reports whether a character belongs to the unpadded base32
// alphabet used for identifiers and tokens.
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
