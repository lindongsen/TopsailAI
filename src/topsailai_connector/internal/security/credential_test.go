package security

import (
	"strings"
	"testing"
)

// TestParseCredentialRoundTrips checks that a generated credential survives the
// documented text form, so the value an operator copies is the value a verifier parses.
func TestParseCredentialRoundTrips(t *testing.T) {
	generated, err := NewCredential()
	if err != nil {
		t.Fatalf("NewCredential() = %v", err)
	}

	parsed, err := ParseCredential(generated.String())
	if err != nil {
		t.Fatalf("ParseCredential(%q) = %v", generated.Redacted(), err)
	}
	if parsed.KeyID != generated.KeyID {
		t.Errorf("key id = %q, want %q", parsed.KeyID, generated.KeyID)
	}
	if parsed.Secret != generated.Secret {
		t.Errorf("secret does not round-trip")
	}
}

// TestParseCredentialRefusesMalformed checks every malformed form the parser documents.
//
// Each case is a refusal rather than a repair, because a repaired credential is a
// credential the operator did not write.
func TestParseCredentialRefusesMalformed(t *testing.T) {
	valid := strings.Repeat("a", MinCredentialSecretLength)
	cases := map[string]string{
		"empty":              "",
		"no dot":             "keyonly",
		"empty key id":       "." + valid,
		"empty secret":       "keyid.",
		"second dot":         "keyid." + valid + ".extra",
		"leading space":      " keyid." + valid,
		"trailing space":     "keyid." + valid + " ",
		"uppercase key id":   "KeyID." + valid,
		"key id with slash":  "key/id." + valid,
		"short secret":       "keyid.short",
		"secret with space":  "keyid." + valid + " x",
		"secret with slash":  "keyid." + valid + "/x",
		"key id starts flag": "-keyid." + valid,
	}
	for name, value := range cases {
		if _, err := ParseCredential(value); err == nil {
			t.Errorf("%s: ParseCredential(%q) = nil error, want a refusal", name, value)
		}
	}
}

// TestCredentialRedactedHidesSecret checks that the printable form keeps the public
// identifier and never contains the secret.
func TestCredentialRedactedHidesSecret(t *testing.T) {
	credential, err := NewCredential()
	if err != nil {
		t.Fatalf("NewCredential() = %v", err)
	}

	redacted := credential.Redacted()
	if !strings.Contains(redacted, credential.KeyID) {
		t.Errorf("redacted form %q does not name the key id %q", redacted, credential.KeyID)
	}
	if strings.Contains(redacted, string(credential.Secret)) {
		t.Errorf("redacted form %q contains the secret", redacted)
	}
}

// TestNewCredentialWithKeyIDKeepsTheName checks that an operator-chosen identifier is
// preserved, because it is what makes an audit record readable.
func TestNewCredentialWithKeyIDKeepsTheName(t *testing.T) {
	credential, err := NewCredentialWithKeyID("operator-dawson")
	if err != nil {
		t.Fatalf("NewCredentialWithKeyID() = %v", err)
	}
	if credential.KeyID != "operator-dawson" {
		t.Errorf("key id = %q, want operator-dawson", credential.KeyID)
	}
	if err := ValidateCredentialSecret(credential.Secret); err != nil {
		t.Errorf("generated secret is unusable: %v", err)
	}
}

// TestNewCredentialWithKeyIDRefusesInvalidName checks that a generated credential and a
// parsed one agree about what a valid identifier is.
func TestNewCredentialWithKeyIDRefusesInvalidName(t *testing.T) {
	for _, keyID := range []string{"", "Upper", "with space", "with/slash", "-leading"} {
		if _, err := NewCredentialWithKeyID(keyID); err == nil {
			t.Errorf("NewCredentialWithKeyID(%q) = nil error, want a refusal", keyID)
		}
	}
}

// TestNewCredentialIsUnique checks that two generated credentials never collide, because
// a collision would make one caller's proof verify against another caller's secret.
func TestNewCredentialIsUnique(t *testing.T) {
	first, err := NewCredential()
	if err != nil {
		t.Fatalf("NewCredential() = %v", err)
	}
	second, err := NewCredential()
	if err != nil {
		t.Fatalf("NewCredential() = %v", err)
	}
	if first.KeyID == second.KeyID {
		t.Errorf("two generated credentials share the key id %q", first.KeyID)
	}
	if first.Secret == second.Secret {
		t.Errorf("two generated credentials share a secret")
	}
}
