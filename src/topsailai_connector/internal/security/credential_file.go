package security

import (
	"bytes"
	"errors"
	"fmt"
	"io"
	"sort"

	"gopkg.in/yaml.v3"
)

// CredentialFileVersion is the only credential file format this build understands.
const CredentialFileVersion = 1

// MaxCredentialFileBytes bounds a credential file.
//
// The bound is applied before decoding, because reading an oversized file into
// memory before deciding it is oversized is the wrong order.
const MaxCredentialFileBytes = 1 << 20

// MaxCredentials bounds the number of credentials one verifier holds.
//
// The bound exists so a credential set cannot grow into an unbounded map that makes
// every lookup and every reload scan an arbitrary amount of memory. It is generous
// for a person and a handful of services, and small enough to state.
const MaxCredentials = 32

// ErrCredentialFileEmpty reports an empty credential document.
//
// An empty file is refused rather than read as an empty set, because an empty set
// refuses every caller and looks exactly like a working verifier that denies
// everything. A file that deliberately holds no credentials states that with an
// empty list.
var ErrCredentialFileEmpty = errors.New("credential file is empty")

// CredentialSet is an immutable snapshot of the credentials one verifier accepts.
//
// A snapshot is published whole and replaced whole, so a request that is already
// being verified keeps the set it started with instead of observing a half-applied
// reload. The set holds secrets, so it is never logged and never rendered.
type CredentialSet struct {
	secrets map[string]Secret
}

// NewCredentialSet builds a set from credentials, refusing duplicates and an
// oversized set.
//
// A duplicate key identifier is refused rather than resolved, because two secrets
// for one public identifier would make "which secret verifies this proof" depend on
// load order, and a rotation would then silently keep the old secret alive.
func NewCredentialSet(credentials []Credential) (*CredentialSet, error) {
	if len(credentials) > MaxCredentials {
		return nil, fmt.Errorf("credential set holds %d credentials, want at most %d", len(credentials), MaxCredentials)
	}
	secrets := make(map[string]Secret, len(credentials))
	for _, credential := range credentials {
		if err := ValidateKeyID(credential.KeyID); err != nil {
			return nil, err
		}
		if err := ValidateCredentialSecret(credential.Secret); err != nil {
			return nil, fmt.Errorf("credential %q: %w", credential.KeyID, err)
		}
		if _, duplicate := secrets[credential.KeyID]; duplicate {
			return nil, fmt.Errorf("credential key id %q appears twice", credential.KeyID)
		}
		secrets[credential.KeyID] = credential.Secret
	}
	return &CredentialSet{secrets: secrets}, nil
}

// Lookup returns the secret for a key identifier.
//
// The lookup is one map read, never a scan through every configured secret. A scan
// would make verification cost grow with the number of credentials and would let a
// timing difference reveal which key identifiers exist.
func (s *CredentialSet) Lookup(keyID string) (Secret, bool) {
	if s == nil {
		return "", false
	}
	secret, present := s.secrets[keyID]
	return secret, present
}

// Len reports how many credentials the set holds.
func (s *CredentialSet) Len() int {
	if s == nil {
		return 0
	}
	return len(s.secrets)
}

// KeyIDs returns the public key identifiers in sorted order, so a startup report and
// a test are both stable. It never returns a secret.
func (s *CredentialSet) KeyIDs() []string {
	if s == nil {
		return nil
	}
	keyIDs := make([]string, 0, len(s.secrets))
	for keyID := range s.secrets {
		keyIDs = append(keyIDs, keyID)
	}
	sort.Strings(keyIDs)
	return keyIDs
}

// credentialFile is the on-disk shape. It is separate from CredentialSet so the
// decoded form can be validated before it becomes something a verifier uses.
type credentialFile struct {
	Version     int                  `yaml:"version"`
	Credentials []credentialDocument `yaml:"credentials"`
}

// credentialDocument is one credential in the file.
type credentialDocument struct {
	KeyID  string `yaml:"key_id"`
	Secret string `yaml:"secret"`
}

// ParseCredentialSet decodes and validates a credential document.
//
// Decoding is strict in both directions: an unknown key is refused, and a document
// with more than one YAML document is refused, because a second document would be
// silently ignored and a credential set that is half-read is a set nobody can
// reason about.
func ParseCredentialSet(content []byte) (*CredentialSet, error) {
	if len(content) > MaxCredentialFileBytes {
		return nil, fmt.Errorf("credential file is %d bytes, want at most %d", len(content), MaxCredentialFileBytes)
	}

	decoder := yaml.NewDecoder(bytes.NewReader(content))
	decoder.KnownFields(true)

	var decoded credentialFile
	if err := decoder.Decode(&decoded); err != nil {
		if errors.Is(err, io.EOF) {
			return nil, ErrCredentialFileEmpty
		}
		return nil, fmt.Errorf("decode credential file: %w", err)
	}

	var extra credentialFile
	if err := decoder.Decode(&extra); err == nil {
		return nil, fmt.Errorf("credential file holds more than one document; only the first would be read")
	} else if !errors.Is(err, io.EOF) {
		return nil, fmt.Errorf("decode credential file: %w", err)
	}

	if decoded.Version == 0 {
		return nil, fmt.Errorf("credential file version is required; a file without a version cannot be migrated")
	}
	if decoded.Version != CredentialFileVersion {
		return nil, fmt.Errorf("credential file version %d is not supported; this build understands %d", decoded.Version, CredentialFileVersion)
	}

	credentials := make([]Credential, 0, len(decoded.Credentials))
	for index, document := range decoded.Credentials {
		if document.KeyID == "" {
			return nil, fmt.Errorf("credential %d has no key_id", index)
		}
		if document.Secret == "" {
			return nil, fmt.Errorf("credential %q has no secret", document.KeyID)
		}
		credentials = append(credentials, Credential{KeyID: document.KeyID, Secret: Secret(document.Secret)})
	}
	return NewCredentialSet(credentials)
}

// FormatCredentialSet renders a credential set as a credential document.
//
// It exists so a management command and a test write the same format the parser
// reads. A second implementation of the format would be a second definition of a
// valid credential file.
func FormatCredentialSet(credentials []Credential) ([]byte, error) {
	if _, err := NewCredentialSet(credentials); err != nil {
		return nil, err
	}
	documents := make([]credentialDocument, 0, len(credentials))
	for _, credential := range credentials {
		documents = append(documents, credentialDocument{KeyID: credential.KeyID, Secret: string(credential.Secret)})
	}
	return yaml.Marshal(credentialFile{Version: CredentialFileVersion, Credentials: documents})
}
