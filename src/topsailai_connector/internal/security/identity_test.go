package security

import (
	"errors"
	"strings"
	"testing"
)

// TestNewNodeIdentity checks that a generated identity is well formed and that
// two generations differ, because an identity that repeats is an identity that
// two Nodes share.
func TestNewNodeIdentity(t *testing.T) {
	first, err := NewNodeIdentity()
	if err != nil {
		t.Fatalf("NewNodeIdentity() = %v", err)
	}
	second, err := NewNodeIdentity()
	if err != nil {
		t.Fatalf("NewNodeIdentity() = %v", err)
	}

	if err := ValidateNodeID(first.ID); err != nil {
		t.Fatalf("generated id %q is invalid: %v", first.ID, err)
	}
	if err := ValidateNodeToken(first.Token); err != nil {
		t.Fatalf("generated token is invalid: %v", err)
	}
	if first.ID == second.ID {
		t.Fatalf("two generated identities share the id %q", first.ID)
	}
	if first.Token.Equal(second.Token) {
		t.Fatal("two generated identities share the token")
	}
	if !strings.HasPrefix(first.ID, NodeIDPrefix) {
		t.Fatalf("generated id %q does not start with %q", first.ID, NodeIDPrefix)
	}
}

// TestNewNodeTokenKeepsID checks that a regeneration that keeps the identifier
// changes the token, because a regeneration that kept the secret would not be a
// regeneration.
func TestNewNodeTokenKeepsID(t *testing.T) {
	original, err := NewNodeIdentity()
	if err != nil {
		t.Fatalf("NewNodeIdentity() = %v", err)
	}

	regenerated, err := NewNodeToken(original.ID)
	if err != nil {
		t.Fatalf("NewNodeToken() = %v", err)
	}

	if regenerated.ID != original.ID {
		t.Fatalf("id = %q, want %q", regenerated.ID, original.ID)
	}
	if regenerated.Token.Equal(original.Token) {
		t.Fatal("regeneration kept the token, want a new one")
	}
}

// TestNewNodeTokenRejectsInvalidID checks that a regeneration cannot preserve a
// name that was never valid, because that would make the parser's rules
// bypassable by regenerating.
func TestNewNodeTokenRejectsInvalidID(t *testing.T) {
	for _, id := range []string{"", "node_", "node_ABC", "other_abc", "node_ab.cd"} {
		if _, err := NewNodeToken(id); err == nil {
			t.Fatalf("NewNodeToken(%q) = nil error, want error", id)
		}
	}
}

// TestNodeIdentityString checks the wire form the operator copies: identifier,
// one dot, token.
func TestNodeIdentityString(t *testing.T) {
	identity := NodeIdentity{ID: "node_abc123", Token: "deadbeef"}
	if got := identity.String(); got != "node_abc123.deadbeef" {
		t.Fatalf("String() = %q, want %q", got, "node_abc123.deadbeef")
	}
}

// TestNodeIdentityRedacted checks that the printable form keeps the identifier
// and hides the token, because the identifier is an address and the token is a
// credential.
func TestNodeIdentityRedacted(t *testing.T) {
	identity := NodeIdentity{ID: "node_abc123", Token: "deadbeefdeadbeef"}
	redacted := identity.Redacted()

	if !strings.Contains(redacted, "node_abc123") {
		t.Fatalf("Redacted() = %q does not contain the identifier", redacted)
	}
	if strings.Contains(redacted, "deadbeef") {
		t.Fatalf("Redacted() = %q contains the token", redacted)
	}
}

// TestParseNodeIdentity checks that a well-formed pair round-trips, so the value
// the Node prints is the value the CLI can parse.
func TestParseNodeIdentity(t *testing.T) {
	original, err := NewNodeIdentity()
	if err != nil {
		t.Fatalf("NewNodeIdentity() = %v", err)
	}

	parsed, err := ParseNodeIdentity(original.String())
	if err != nil {
		t.Fatalf("ParseNodeIdentity() = %v", err)
	}
	if parsed.ID != original.ID {
		t.Fatalf("id = %q, want %q", parsed.ID, original.ID)
	}
	if !parsed.Token.Equal(original.Token) {
		t.Fatal("parsed token does not match the generated token")
	}
}

// TestParseNodeIdentityRejectsMalformed checks every malformed form. Each is a
// refusal rather than a repair, because a repaired pair is a pair the operator
// did not write.
func TestParseNodeIdentityRejectsMalformed(t *testing.T) {
	cases := []struct {
		name string
		pair string
	}{
		{name: "empty", pair: ""},
		{name: "no dot", pair: "node_abc123"},
		{name: "empty identifier half", pair: ".deadbeef"},
		{name: "empty token half", pair: "node_abc123."},
		{name: "second dot in token half", pair: "node_abc123.dead.beef"},
		{name: "missing prefix", pair: "abc123.deadbeef"},
		{name: "uppercase identifier", pair: "node_ABC123.deadbeef"},
		{name: "uppercase token", pair: "node_abc123.DEADBEEF"},
		{name: "leading whitespace", pair: " node_abc123.deadbeef"},
		{name: "trailing whitespace", pair: "node_abc123.deadbeef "},
		{name: "trailing newline", pair: "node_abc123.deadbeef\n"},
		{name: "space inside", pair: "node_abc123.dead beef"},
		{name: "tab inside", pair: "node_abc123.dead\tbeef"},
		{name: "nul byte", pair: "node_abc123.dead\x00beef"},
		{name: "path separator in identifier", pair: "node_ab/c123.deadbeef"},
		{name: "colon in token", pair: "node_abc123.dead:beef"},
	}

	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			if _, err := ParseNodeIdentity(testCase.pair); err == nil {
				t.Fatalf("ParseNodeIdentity(%q) = nil error, want error", testCase.pair)
			} else if !errors.Is(err, ErrMalformedPair) {
				t.Fatalf("ParseNodeIdentity(%q) = %v, want ErrMalformedPair", testCase.pair, err)
			}
		})
	}
}

// TestParseNodeIdentitySplitsOnFirstDot checks the split position. Splitting on
// the last dot would silently move the boundary if a token ever contained one,
// and the two halves would then be different values than the ones generated.
func TestParseNodeIdentitySplitsOnFirstDot(t *testing.T) {
	_, err := ParseNodeIdentity("node_abc123.dead.beef")
	if err == nil {
		t.Fatal("ParseNodeIdentity() accepted a pair with two dots, want error")
	}
	if !strings.Contains(err.Error(), "second dot") {
		t.Fatalf("error %q does not name the second dot", err)
	}
}

// TestValidateNodeID checks the identifier rules, because an identifier that is
// not recognisable cannot be routed and cannot be audited.
func TestValidateNodeID(t *testing.T) {
	cases := []struct {
		name    string
		id      string
		wantErr bool
	}{
		{name: "valid", id: "node_0123456789abcdefghijklmnop", wantErr: false},
		{name: "valid with digits only", id: "node_01234567890123456789012345", wantErr: false},
		{name: "empty", id: "", wantErr: true},
		{name: "prefix only", id: "node_", wantErr: true},
		{name: "missing prefix", id: "0123456789abcdefghijklmnop", wantErr: true},
		{name: "wrong prefix", id: "nodex_0123456789abcdefghijklmnop", wantErr: true},
		{name: "uppercase body", id: "node_0123456789ABCDEFGHIJKLMNOP", wantErr: true},
		{name: "dash in body", id: "node_0123456789abcdefghijklmno-", wantErr: true},
		{name: "dot in body", id: "node_0123456789abcdefghijklmno.", wantErr: true},
		{name: "space in body", id: "node_0123456789abcdefghijklmno ", wantErr: true},
		{name: "body one character short", id: "node_0123456789abcdefghijklmno", wantErr: true},
		{name: "body one character long", id: "node_0123456789abcdefghijklmnopq", wantErr: true},
		{name: "truncated identifier", id: "node_short", wantErr: true},
	}

	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			err := ValidateNodeID(testCase.id)
			if testCase.wantErr && err == nil {
				t.Fatalf("ValidateNodeID(%q) = nil, want error", testCase.id)
			}
			if !testCase.wantErr && err != nil {
				t.Fatalf("ValidateNodeID(%q) = %v, want nil", testCase.id, err)
			}
		})
	}
}

// TestValidateNodeToken checks that a token is non-empty and uses the generated
// alphabet, so a value mangled in transit is refused instead of compared.
func TestValidateNodeToken(t *testing.T) {
	cases := []struct {
		name    string
		token   Secret
		wantErr bool
	}{
		{name: "valid", token: "deadbeef", wantErr: false},
		{name: "empty", token: "", wantErr: true},
		{name: "uppercase", token: "DEADBEEF", wantErr: true},
		{name: "dash", token: "dead-beef", wantErr: true},
		{name: "dot", token: "dead.beef", wantErr: true},
		{name: "space", token: "dead beef", wantErr: true},
	}

	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			err := ValidateNodeToken(testCase.token)
			if testCase.wantErr && err == nil {
				t.Fatalf("ValidateNodeToken(%q) = nil, want error", testCase.token.Redacted())
			}
			if !testCase.wantErr && err != nil {
				t.Fatalf("ValidateNodeToken(%q) = %v, want nil", testCase.token.Redacted(), err)
			}
		})
	}
}
