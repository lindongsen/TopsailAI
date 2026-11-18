package security

import (
	"errors"
	"fmt"
	"strings"
)

// MaxKeyIDLength bounds a credential key identifier.
//
// The bound exists so a key identifier that cannot be a map key of a sane size is
// refused before it reaches a lookup, rather than after. It is generous enough for
// a person's name and a service name, and small enough that a log line stays
// readable.
const MaxKeyIDLength = 64

// MinCredentialSecretLength is the shortest HMAC secret accepted.
//
// A credential secret is an HMAC key, so its length is the only thing standing
// between a guess and a forgery. 32 characters of the accepted alphabet carry at
// least 160 bits when the operator generates them from a random source, which is
// the floor this check enforces.
const MinCredentialSecretLength = 32

// ErrMalformedCredential reports a credential that could not be split into a key
// identifier and a secret. Every malformed form produces this one error, because a
// caller that can tell "no dot" from "empty secret" learns the shape of a valid
// credential.
var ErrMalformedCredential = errors.New("malformed key_id.secret credential")

// Credential is one copyable caller credential: a public key identifier and the
// secret that proves possession of it.
//
// The two halves have different jobs. The key identifier is public: it selects one
// secret from a verifier's set and may appear in an audit record. The secret is the
// HMAC key and never leaves the signer and the verifier. Keeping them in one string
// is a copying convenience, not a claim that they are the same kind of value.
type Credential struct {
	// KeyID is the public half. It is what a verifier looks up.
	KeyID string
	// Secret is the HMAC key. It is never logged and never transmitted.
	Secret Secret
}

// ParseCredential splits a key_id.secret credential.
//
// Every rule is a refusal rather than a repair, because a repaired credential is a
// credential the operator did not write:
//
//   - The split is on the first dot. A key identifier cannot contain a dot, so the
//     boundary is unambiguous; splitting on the last dot would move it if a secret
//     ever contained one.
//   - A credential with no dot is refused, because a lone key identifier is not a
//     secret and a lone secret is not selectable.
//   - An empty half is refused, because an empty secret would be an HMAC key of
//     length zero.
//   - A second dot in the secret half is refused, because the accepted secret
//     alphabet has no dot, so a dot there means the value was mangled in transit.
//   - Whitespace is refused rather than trimmed. Trimming would hide a copy-paste
//     error that would otherwise surface as a confusing authentication failure.
func ParseCredential(value string) (Credential, error) {
	if value == "" {
		return Credential{}, fmt.Errorf("%w: value is empty", ErrMalformedCredential)
	}
	if strings.TrimSpace(value) != value {
		return Credential{}, fmt.Errorf("%w: value has leading or trailing whitespace", ErrMalformedCredential)
	}

	index := strings.Index(value, ".")
	if index < 0 {
		return Credential{}, fmt.Errorf("%w: no dot separating the key id from the secret", ErrMalformedCredential)
	}
	keyID := value[:index]
	secret := value[index+1:]
	if keyID == "" {
		return Credential{}, fmt.Errorf("%w: key id half is empty", ErrMalformedCredential)
	}
	if secret == "" {
		return Credential{}, fmt.Errorf("%w: secret half is empty", ErrMalformedCredential)
	}
	if strings.Contains(secret, ".") {
		return Credential{}, fmt.Errorf("%w: secret half contains a second dot", ErrMalformedCredential)
	}
	if err := ValidateKeyID(keyID); err != nil {
		return Credential{}, fmt.Errorf("%w: %v", ErrMalformedCredential, err)
	}
	if err := ValidateCredentialSecret(Secret(secret)); err != nil {
		return Credential{}, fmt.Errorf("%w: %v", ErrMalformedCredential, err)
	}
	return Credential{KeyID: keyID, Secret: Secret(secret)}, nil
}

// String renders the credential in the form the operator copies. It is the only
// method that returns the secret, so a caller that wants the secret has to ask for
// the whole credential and split it deliberately.
func (c Credential) String() string {
	return c.KeyID + "." + string(c.Secret)
}

// Redacted renders the credential with the secret replaced, so a credential can
// appear in a log or an error message. The key identifier is kept because it is
// public and is what an operator needs to identify the caller.
func (c Credential) Redacted() string {
	return c.KeyID + "." + c.Secret.Redacted()
}

// ValidateKeyID checks that a key identifier is usable as a public selector.
//
// The alphabet is a whitelist: lowercase letters, digits, `-` and `_`. A whitelist
// has to anticipate nothing, while a blacklist has to anticipate every character a
// shell, a URL or a log format treats specially. The first character must be a
// letter or a digit so a key identifier can never look like a flag.
func ValidateKeyID(keyID string) error {
	if keyID == "" {
		return errors.New("key id is empty")
	}
	if len(keyID) > MaxKeyIDLength {
		return fmt.Errorf("key id is %d bytes, want at most %d", len(keyID), MaxKeyIDLength)
	}
	for index, character := range keyID {
		if !isKeyIDCharacter(character) {
			return fmt.Errorf("key id %q contains %q, which is not a lowercase letter, a digit, '-' or '_'", keyID, character)
		}
		if index == 0 && (character == '-' || character == '_') {
			return fmt.Errorf("key id %q starts with %q, which makes it look like a flag", keyID, character)
		}
	}
	return nil
}

// isKeyIDCharacter reports whether a character belongs to the key identifier
// alphabet.
func isKeyIDCharacter(character rune) bool {
	switch {
	case character >= 'a' && character <= 'z':
		return true
	case character >= '0' && character <= '9':
		return true
	case character == '-', character == '_':
		return true
	default:
		return false
	}
}

// ValidateCredentialSecret checks that a credential secret is usable as an HMAC
// key.
//
// The alphabet is base64url without padding: letters, digits, `-` and `_`. That
// alphabet survives a URL, a shell argument, a JSON string and a Windows file name
// without escaping, and it excludes the dot that separates the two halves of a
// credential. Uppercase is accepted because a secret is compared byte for byte and
// is never used as a path.
func ValidateCredentialSecret(secret Secret) error {
	value := string(secret)
	if value == "" {
		return errors.New("credential secret is empty")
	}
	if len(value) < MinCredentialSecretLength {
		return fmt.Errorf("credential secret is %d bytes, want at least %d", len(value), MinCredentialSecretLength)
	}
	for _, character := range value {
		if !isCredentialSecretCharacter(character) {
			return fmt.Errorf("credential secret contains %q, which is not a letter, a digit, '-' or '_'", character)
		}
	}
	return nil
}

// isCredentialSecretCharacter reports whether a character belongs to the credential
// secret alphabet.
func isCredentialSecretCharacter(character rune) bool {
	switch {
	case character >= 'a' && character <= 'z':
		return true
	case character >= 'A' && character <= 'Z':
		return true
	case character >= '0' && character <= '9':
		return true
	case character == '-', character == '_':
		return true
	default:
		return false
	}
}
