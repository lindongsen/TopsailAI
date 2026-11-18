package security

import (
	"bytes"
	"errors"
	"fmt"
	"io"

	"gopkg.in/yaml.v3"
)

// ParseCredentialList decodes a credential document into the raw credentials it holds.
//
// It exists for the management commands, which must rewrite the file and therefore need
// the secrets it already contains. It is deliberately separate from ParseCredentialSet:
// a set is what a verifier uses, and a verifier has no reason to read a secret back. A
// set that could be rendered would be a set that can be printed, so the two entry points
// keep the readable form and the verifying form apart.
//
// The validation is the same as ParseCredentialSet, so a file the management command
// accepts is a file the verifier accepts.
func ParseCredentialList(content []byte) ([]Credential, error) {
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
	if _, err := NewCredentialSet(credentials); err != nil {
		return nil, err
	}
	return credentials, nil
}
