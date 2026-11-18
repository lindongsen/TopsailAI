package security

import (
	"strings"
	"testing"
)

// TestCredentialSetRoundTripsThroughTheFileFormat checks that the formatter writes what
// the parser reads, so a management command and a verifier cannot disagree.
func TestCredentialSetRoundTripsThroughTheFileFormat(t *testing.T) {
	first, err := NewCredentialWithKeyID("operator-dawson")
	if err != nil {
		t.Fatalf("NewCredentialWithKeyID() = %v", err)
	}
	second, err := NewCredentialWithKeyID("ci-system")
	if err != nil {
		t.Fatalf("NewCredentialWithKeyID() = %v", err)
	}

	content, err := FormatCredentialSet([]Credential{first, second})
	if err != nil {
		t.Fatalf("FormatCredentialSet() = %v", err)
	}

	set, err := ParseCredentialSet(content)
	if err != nil {
		t.Fatalf("ParseCredentialSet() = %v", err)
	}
	if set.Len() != 2 {
		t.Errorf("set holds %d credentials, want 2", set.Len())
	}
	for _, credential := range []Credential{first, second} {
		secret, present := set.Lookup(credential.KeyID)
		if !present {
			t.Errorf("set does not hold %q", credential.KeyID)
			continue
		}
		if secret != credential.Secret {
			t.Errorf("secret for %q does not round-trip", credential.KeyID)
		}
	}
}

// TestParseCredentialSetRefusesMalformed checks the strict decoding rules.
//
// Each case is a file that a permissive decoder would have accepted, which is why the
// decoder is strict: a security configuration that is half-read is a configuration nobody
// can reason about.
func TestParseCredentialSetRefusesMalformed(t *testing.T) {
	valid := "version: 1\ncredentials:\n  - key_id: operator\n    secret: " + strings.Repeat("a", MinCredentialSecretLength) + "\n"

	cases := map[string]string{
		"empty":              "",
		"no version":         "credentials:\n  - key_id: operator\n    secret: " + strings.Repeat("a", MinCredentialSecretLength) + "\n",
		"wrong version":      strings.Replace(valid, "version: 1", "version: 2", 1),
		"unknown key":        valid + "extra: 1\n",
		"missing key id":     "version: 1\ncredentials:\n  - secret: " + strings.Repeat("a", MinCredentialSecretLength) + "\n",
		"missing secret":     "version: 1\ncredentials:\n  - key_id: operator\n",
		"duplicate key id":   "version: 1\ncredentials:\n  - key_id: operator\n    secret: " + strings.Repeat("a", MinCredentialSecretLength) + "\n  - key_id: operator\n    secret: " + strings.Repeat("b", MinCredentialSecretLength) + "\n",
		"short secret":       "version: 1\ncredentials:\n  - key_id: operator\n    secret: short\n",
		"uppercase key id":   "version: 1\ncredentials:\n  - key_id: Operator\n    secret: " + strings.Repeat("a", MinCredentialSecretLength) + "\n",
		"two documents":      valid + "---\n" + valid,
	}
	for name, content := range cases {
		if _, err := ParseCredentialSet([]byte(content)); err == nil {
			t.Errorf("%s: ParseCredentialSet() = nil error, want a refusal", name)
		}
	}
}

// TestParseCredentialSetAcceptsAnEmptyList checks that a file which deliberately holds no
// credentials is accepted.
//
// An empty file is refused, because it looks exactly like a working verifier that denies
// everything. A file that states an empty list is a recorded decision.
func TestParseCredentialSetAcceptsAnEmptyList(t *testing.T) {
	set, err := ParseCredentialSet([]byte("version: 1\ncredentials: []\n"))
	if err != nil {
		t.Fatalf("ParseCredentialSet(empty list) = %v", err)
	}
	if set.Len() != 0 {
		t.Errorf("set holds %d credentials, want 0", set.Len())
	}
}

// TestCredentialSetLookupIsExact checks that a lookup does not match a prefix or a
// different case, because a scan or a fuzzy match would let a timing difference reveal
// which key identifiers exist.
func TestCredentialSetLookupIsExact(t *testing.T) {
	credential, err := NewCredentialWithKeyID("operator")
	if err != nil {
		t.Fatalf("NewCredentialWithKeyID() = %v", err)
	}
	set, err := NewCredentialSet([]Credential{credential})
	if err != nil {
		t.Fatalf("NewCredentialSet() = %v", err)
	}

	if _, present := set.Lookup("operator"); !present {
		t.Errorf("Lookup(exact) = absent, want present")
	}
	for _, keyID := range []string{"operato", "operator2", "Operator", ""} {
		if _, present := set.Lookup(keyID); present {
			t.Errorf("Lookup(%q) = present, want absent", keyID)
		}
	}
}

// TestCredentialSetKeyIDsAreSorted checks that the public identifiers are reported in a
// stable order, so a startup report and a test are both reproducible.
func TestCredentialSetKeyIDsAreSorted(t *testing.T) {
	first, err := NewCredentialWithKeyID("zulu")
	if err != nil {
		t.Fatalf("NewCredentialWithKeyID() = %v", err)
	}
	second, err := NewCredentialWithKeyID("alpha")
	if err != nil {
		t.Fatalf("NewCredentialWithKeyID() = %v", err)
	}
	set, err := NewCredentialSet([]Credential{first, second})
	if err != nil {
		t.Fatalf("NewCredentialSet() = %v", err)
	}

	keyIDs := set.KeyIDs()
	if len(keyIDs) != 2 || keyIDs[0] != "alpha" || keyIDs[1] != "zulu" {
		t.Errorf("KeyIDs() = %v, want [alpha zulu]", keyIDs)
	}
}

// TestNewCredentialSetRefusesTooMany checks the bound on the number of credentials.
func TestNewCredentialSetRefusesTooMany(t *testing.T) {
	credentials := make([]Credential, 0, MaxCredentials+1)
	for index := 0; index <= MaxCredentials; index++ {
		credential, err := NewCredential()
		if err != nil {
			t.Fatalf("NewCredential() = %v", err)
		}
		credentials = append(credentials, credential)
	}
	if _, err := NewCredentialSet(credentials); err == nil {
		t.Errorf("NewCredentialSet(%d credentials) = nil error, want a refusal", len(credentials))
	}
}

// TestParseCredentialListReturnsTheSecrets checks that the management entry point can read
// back what it must rewrite.
func TestParseCredentialListReturnsTheSecrets(t *testing.T) {
	credential, err := NewCredentialWithKeyID("operator")
	if err != nil {
		t.Fatalf("NewCredentialWithKeyID() = %v", err)
	}
	content, err := FormatCredentialSet([]Credential{credential})
	if err != nil {
		t.Fatalf("FormatCredentialSet() = %v", err)
	}

	credentials, err := ParseCredentialList(content)
	if err != nil {
		t.Fatalf("ParseCredentialList() = %v", err)
	}
	if len(credentials) != 1 {
		t.Fatalf("ParseCredentialList() returned %d credentials, want 1", len(credentials))
	}
	if credentials[0] != credential {
		t.Errorf("ParseCredentialList() = %+v, want %+v", credentials[0], credential)
	}
}

// TestParseCredentialListRefusesMalformed checks that the management entry point is held
// to the same rules as the verifier.
func TestParseCredentialListRefusesMalformed(t *testing.T) {
	if _, err := ParseCredentialList([]byte("")); err == nil {
		t.Errorf("ParseCredentialList(empty) = nil error, want a refusal")
	}
	if _, err := ParseCredentialList([]byte("version: 1\ncredentials:\n  - key_id: operator\n    secret: short\n")); err == nil {
		t.Errorf("ParseCredentialList(short secret) = nil error, want a refusal")
	}
}
