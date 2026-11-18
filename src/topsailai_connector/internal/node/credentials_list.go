package node

import (
	"errors"
	"fmt"
	"os"

	"topsailai_connector/internal/security"
)

// LoadCredentialList reads the credential file and returns the credentials it holds.
//
// It exists for the management commands, which must rewrite the file and therefore need
// the secrets it already contains. The verifier uses LoadCredentials instead, because a
// verifier has no reason to read a secret back: a set that could be rendered would be a
// set that can be printed.
//
// The validation is the same as LoadCredentials, so a file the management command accepts
// is a file the verifier accepts.
func LoadCredentialList(path string) ([]security.Credential, error) {
	content, err := os.ReadFile(path)
	if err != nil {
		if errors.Is(err, os.ErrNotExist) {
			return nil, fmt.Errorf("%w: %s", ErrCredentialsMissing, path)
		}
		return nil, fmt.Errorf("read credential file %q: %w", path, err)
	}
	if err := checkCredentialFileMode(path); err != nil {
		return nil, err
	}
	credentials, err := security.ParseCredentialList(content)
	if err != nil {
		return nil, fmt.Errorf("credential file %q: %w", path, err)
	}
	return credentials, nil
}
