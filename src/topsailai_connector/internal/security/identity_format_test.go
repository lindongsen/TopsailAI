package security

import (
	"strings"
	"testing"
)

// The numbers below are written as literals on purpose. A test that asserted
// len(id) == nodeIDBodyLength would move with the constant it is meant to pin,
// so a change to the entropy would keep the test green while the documented
// format silently changed. These literals are the contract: the design document
// states 26 and 52, and a change here must be a deliberate change to both.
const (
	documentedIDBodyLength = 26
	documentedIDLength     = len(NodeIDPrefix) + documentedIDBodyLength // 31
	documentedTokenLength  = 52
	documentedPairLength   = documentedIDLength + 1 + documentedTokenLength // 84
)

// documentedPair is the example the design document shows. It is a real pair
// shape, not a placeholder, so a reader who copies it gets a value the parser
// accepts.
const documentedPair = "node_oswngej2n7glyprc3cljp6an4i.br4l25x274uyk4wej5s42ss6kpqtb4vhevxwxmwczhrhfmawxnkq"

// TestGeneratedIdentityMatchesDocumentedLengths pins the length of every part a
// generated identity produces. The design document states these numbers, so a
// generator that changed them without changing the document would be a silent
// divergence between what the system emits and what it says it emits.
func TestGeneratedIdentityMatchesDocumentedLengths(t *testing.T) {
	identity, err := NewNodeIdentity()
	if err != nil {
		t.Fatalf("NewNodeIdentity() = %v", err)
	}

	if got := len(identity.ID); got != documentedIDLength {
		t.Errorf("len(id) = %d, want %d", got, documentedIDLength)
	}
	if got := len(identity.ID) - len(NodeIDPrefix); got != documentedIDBodyLength {
		t.Errorf("len(id body) = %d, want %d", got, documentedIDBodyLength)
	}
	if got := len(identity.Token); got != documentedTokenLength {
		t.Errorf("len(token) = %d, want %d", got, documentedTokenLength)
	}
	if got := len(identity.String()); got != documentedPairLength {
		t.Errorf("len(pair) = %d, want %d", got, documentedPairLength)
	}
}

// TestGeneratedIdentityUsesOnlyLowercaseBase32 pins the alphabet. The document
// states that both halves are unpadded lowercase base32, which is `a-z` and
// `0-9` and nothing else. A generator that emitted `-`, `_` or an uppercase
// letter would still pass every other test in this package, because the
// validator and the generator share the same alphabet helper.
//
// The sample is deliberately large. A base64url generator emits `-` or `_` in
// only a small fraction of values, so a single sample can pass by luck: the
// first version of this test did exactly that and stayed green under a
// base64url mutation. Sampling many identities makes the escape rate
// negligible rather than merely unlikely.
func TestGeneratedIdentityUsesOnlyLowercaseBase32(t *testing.T) {
	const samples = 200

	for sample := 0; sample < samples; sample++ {
		identity, err := NewNodeIdentity()
		if err != nil {
			t.Fatalf("NewNodeIdentity() = %v", err)
		}

		for _, half := range []struct {
			name  string
			value string
		}{
			{"id body", identity.ID[len(NodeIDPrefix):]},
			{"token", string(identity.Token)},
		} {
			for _, character := range half.value {
				if !isLowercaseBase32(character) {
					t.Fatalf("sample %d: %s contains %q, which is not in a-z0-9", sample, half.name, character)
				}
			}
		}
	}
}

// TestDocumentedPairParses checks that the example printed in the design
// document is a pair the parser accepts. A document that shows a value the
// parser refuses teaches a reader to write a value the system rejects.
func TestDocumentedPairParses(t *testing.T) {
	identity, err := ParseNodeIdentity(documentedPair)
	if err != nil {
		t.Fatalf("ParseNodeIdentity(documented example) = %v", err)
	}
	if got := len(identity.ID); got != documentedIDLength {
		t.Errorf("len(id) = %d, want %d", got, documentedIDLength)
	}
	if got := len(identity.Token); got != documentedTokenLength {
		t.Errorf("len(token) = %d, want %d", got, documentedTokenLength)
	}
	if identity.String() != documentedPair {
		t.Errorf("round trip = %q, want %q", identity.String(), documentedPair)
	}
}

// TestTokenAlphabetRefusesBase64Characters pins the characters the document says
// are excluded. Base64url would accept `-` and `_`, and base64 would accept `+`,
// `/` and `=`. Each of those is refused, so a client written against a base64url
// reading of the document fails loudly instead of producing a token the Node
// silently rejects later.
func TestTokenAlphabetRefusesBase64Characters(t *testing.T) {
	valid := strings.Repeat("a", documentedTokenLength)

	for _, character := range []string{"-", "_", "+", "/", "=", "A", "Z", "0"} {
		token := valid[:documentedTokenLength-1] + character
		err := ValidateNodeToken(Secret(token))
		wantRefused := character != "0"
		if wantRefused && err == nil {
			t.Errorf("ValidateNodeToken(token ending %q) = nil, want a refusal", character)
		}
		if !wantRefused && err != nil {
			t.Errorf("ValidateNodeToken(token ending %q) = %v, want nil", character, err)
		}
	}
}

// TestIdentifierBodyLengthIsEnforced pins the asymmetry the document states: the
// identifier length is checked, the token length is not. A truncated identifier
// addresses nothing, so it is refused at parse time; a token of an unexpected
// length is still comparable, so it is accepted and fails at comparison.
func TestIdentifierBodyLengthIsEnforced(t *testing.T) {
	body := strings.Repeat("a", documentedIDBodyLength)

	if err := ValidateNodeID(NodeIDPrefix + body); err != nil {
		t.Fatalf("ValidateNodeID(full length body) = %v, want nil", err)
	}

	for _, length := range []int{documentedIDBodyLength - 1, documentedIDBodyLength + 1} {
		short := strings.Repeat("a", length)
		if err := ValidateNodeID(NodeIDPrefix + short); err == nil {
			t.Errorf("ValidateNodeID(body of %d characters) = nil, want a refusal", length)
		}
	}

	// The token length is deliberately unchecked, so a short token is accepted
	// by the validator and refused only when it fails to compare.
	if err := ValidateNodeToken(Secret("short")); err != nil {
		t.Errorf("ValidateNodeToken(short token) = %v, want nil", err)
	}
}

// isLowercaseBase32 reports whether a character belongs to the alphabet the
// design document states. It is written here rather than reused from the
// implementation so the test states the contract instead of restating the code.
func isLowercaseBase32(character rune) bool {
	return (character >= 'a' && character <= 'z') || (character >= '0' && character <= '9')
}
