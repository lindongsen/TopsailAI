package security

import (
	"strings"
	"testing"
)

// TestSecretEqual checks that a secret matches only its own value. A comparison
// that accepted a prefix, a case variation or a trimmed value would turn a 256
// bit secret into something an attacker can guess.
func TestSecretEqual(t *testing.T) {
	configured := Secret("0123456789abcdef0123456789abcdef")

	cases := []struct {
		name      string
		candidate Secret
		want      bool
	}{
		{name: "identical", candidate: configured, want: true},
		{name: "different last byte", candidate: "0123456789abcdef0123456789abcdee", want: false},
		{name: "different first byte", candidate: "1123456789abcdef0123456789abcdef", want: false},
		{name: "prefix only", candidate: "0123456789abcdef", want: false},
		{name: "configured value plus suffix", candidate: "0123456789abcdef0123456789abcdefx", want: false},
		{name: "uppercase variation", candidate: "0123456789ABCDEF0123456789ABCDEF", want: false},
		{name: "empty candidate", candidate: "", want: false},
		{name: "whitespace padded", candidate: " 0123456789abcdef0123456789abcdef", want: false},
	}

	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			if got := configured.Equal(testCase.candidate); got != testCase.want {
				t.Fatalf("Equal(%q) = %v, want %v", testCase.candidate.Redacted(), got, testCase.want)
			}
		})
	}
}

// TestSecretEqualEmptyConfigured checks that an empty configured secret matches
// nothing, including another empty value. An empty secret is a startup failure,
// so this case exists to prove the comparison is not the place where an empty
// value becomes an accepted one.
func TestSecretEqualEmptyConfigured(t *testing.T) {
	var configured Secret
	if configured.Equal("") {
		t.Fatal("empty configured secret matched an empty candidate, want mismatch")
	}
	if configured.Equal("anything") {
		t.Fatal("empty configured secret matched a candidate, want mismatch")
	}
}

// TestSecretEqualIsSymmetric checks that the comparison does not depend on which
// side is the configured value, because a one-way comparison would be a
// comparison that can be defeated by swapping the arguments.
func TestSecretEqualIsSymmetric(t *testing.T) {
	left := Secret("0123456789abcdef0123456789abcdef")
	right := Secret("fedcba9876543210fedcba9876543210")

	if left.Equal(right) != right.Equal(left) {
		t.Fatal("Equal is not symmetric")
	}
	if left.Equal(left) != right.Equal(right) {
		t.Fatal("Equal does not match a value against itself")
	}
}

// TestSecretValidate checks the startup rules. An empty secret must fail rather
// than disable the check, because an unset environment variable is the most
// likely way to accidentally open the system.
func TestSecretValidate(t *testing.T) {
	cases := []struct {
		name    string
		secret  Secret
		wantErr bool
	}{
		{name: "valid", secret: "0123456789abcdef", wantErr: false},
		{name: "exactly minimum length", secret: Secret(strings.Repeat("a", MinSecretLength)), wantErr: false},
		{name: "empty", secret: "", wantErr: true},
		{name: "one byte short", secret: Secret(strings.Repeat("a", MinSecretLength-1)), wantErr: true},
		{name: "trailing newline", secret: "0123456789abcdef\n", wantErr: true},
		{name: "leading space", secret: " 0123456789abcdef", wantErr: true},
	}

	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			err := testCase.secret.Validate("tunnel_token")
			if testCase.wantErr && err == nil {
				t.Fatalf("Validate() = nil for %s, want error", testCase.secret.Redacted())
			}
			if !testCase.wantErr && err != nil {
				t.Fatalf("Validate() = %v, want nil", err)
			}
		})
	}
}

// TestSecretValidateNamesTheVariable checks that the startup error names the
// variable, because an operator who cannot tell which secret is wrong will
// disable both.
func TestSecretValidateNamesTheVariable(t *testing.T) {
	err := Secret("").Validate("client_token")
	if err == nil {
		t.Fatal("Validate() = nil, want error")
	}
	if !strings.Contains(err.Error(), "client_token") {
		t.Fatalf("error %q does not name the variable", err)
	}
}

// TestSecretRedactedNeverContainsTheValue checks that the only printable form of
// a secret does not contain the secret. This is the property that makes it safe
// to put a secret in a log line.
func TestSecretRedactedNeverContainsTheValue(t *testing.T) {
	value := "0123456789abcdef0123456789abcdef"
	redacted := Secret(value).Redacted()

	if strings.Contains(redacted, value) {
		t.Fatalf("Redacted() = %q contains the secret", redacted)
	}
	if strings.Contains(redacted, value[:8]) {
		t.Fatalf("Redacted() = %q contains a prefix of the secret", redacted)
	}
	if Secret("").Redacted() != "<empty>" {
		t.Fatalf("Redacted() = %q for an empty secret, want <empty>", Secret("").Redacted())
	}
}
