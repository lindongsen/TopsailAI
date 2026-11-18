package security

import (
	"crypto/rand"
	"encoding/base64"
	"fmt"
	"strings"
)

// credentialSecretBytes is the entropy behind a generated credential secret.
//
// 32 bytes is 256 bits, which is the same strength the Node token used to carry.
// The value is an HMAC key, so its length is the only thing standing between a
// guess and a forgery.
const credentialSecretBytes = 32

// credentialSecretEncoding is unpadded base64url: letters, digits, `-` and `_`.
//
// The alphabet is chosen so a secret survives a URL, a shell argument, a JSON
// string and a Windows file name without escaping, and so it never contains the dot
// that separates the two halves of a credential.
var credentialSecretEncoding = base64.RawURLEncoding

// NewCredential generates a fresh credential with a random key identifier and a
// random secret.
//
// The key identifier is random rather than derived from a hostname or a user name,
// because a derived identifier would leak host information and would collide when
// two callers share a name. The operator may rename it afterwards; the identifier is
// public, so renaming it is a documentation change rather than a credential change.
func NewCredential() (Credential, error) {
	keyID, err := newKeyID()
	if err != nil {
		return Credential{}, err
	}
	secret, err := newCredentialSecret()
	if err != nil {
		return Credential{}, err
	}
	return Credential{KeyID: keyID, Secret: secret}, nil
}

// NewCredentialWithKeyID generates a fresh secret for a caller-chosen key
// identifier.
//
// It exists so an operator can name a credential after the person or service that
// holds it, which is what makes an audit record readable. The identifier is
// validated by the same rule a parsed credential uses, so a generated credential and
// a parsed one cannot disagree about what a valid identifier is.
func NewCredentialWithKeyID(keyID string) (Credential, error) {
	if err := ValidateKeyID(keyID); err != nil {
		return Credential{}, err
	}
	secret, err := newCredentialSecret()
	if err != nil {
		return Credential{}, err
	}
	return Credential{KeyID: keyID, Secret: secret}, nil
}

// newKeyID returns a random public key identifier.
//
// The identifier is 16 random bytes encoded as unpadded base64url and lowercased,
// prefixed with `key_`. The prefix makes a key identifier recognisable in a log, so
// a value that selects a secret cannot be mistaken for the secret itself.
func newKeyID() (string, error) {
	buffer := make([]byte, 16)
	if _, err := rand.Read(buffer); err != nil {
		return "", fmt.Errorf("generate credential key id: %w", err)
	}
	return "key_" + strings.ToLower(credentialSecretEncoding.EncodeToString(buffer)), nil
}

// newCredentialSecret returns a random credential secret.
func newCredentialSecret() (Secret, error) {
	buffer := make([]byte, credentialSecretBytes)
	if _, err := rand.Read(buffer); err != nil {
		return "", fmt.Errorf("generate credential secret: %w", err)
	}
	return Secret(credentialSecretEncoding.EncodeToString(buffer)), nil
}
