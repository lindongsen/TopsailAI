package node

import (
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"runtime"

	"topsailai_connector/internal/security"
)

// IdentityFileName is the file inside the config directory that holds the node id.
//
// The file holds an address, not a credential. It lives in a file rather than in the
// environment because the Node rewrites it itself when the operator regenerates it,
// and because a value the Node owns belongs in a file the Node owns rather than in
// the environment of whatever process launched it.
const IdentityFileName = "identity"

// identityFileMode is the mode the identity file is created with. The value is not
// a secret, but it names the Node, so it is kept owner-only for the same reason a
// host name in a private file is: it is nobody else's business which Nodes exist.
const identityFileMode = 0o600

// ErrIdentityMissing reports that no identity file exists yet. It is a distinct
// error because the caller's response is different: a missing identity is
// generated, while a malformed identity is a startup failure.
var ErrIdentityMissing = errors.New("node identity file is missing")

// IdentityPath returns the identity file path inside a config directory.
func IdentityPath(configDir string) string {
	return filepath.Join(configDir, IdentityFileName)
}

// LoadIdentity reads the node id from the identity file at path.
//
// Every failure is a refusal rather than a repair. A malformed file is not
// regenerated, because regenerating would silently invalidate the identifier the
// operator already copied into a CLI, and the operator would see a confusing
// routing failure instead of the real cause.
func LoadIdentity(path string) (string, error) {
	content, err := os.ReadFile(path)
	if err != nil {
		if errors.Is(err, os.ErrNotExist) {
			return "", fmt.Errorf("%w: %s", ErrIdentityMissing, path)
		}
		return "", fmt.Errorf("read identity file %q: %w", path, err)
	}

	if err := checkIdentityFileMode(path); err != nil {
		return "", err
	}

	nodeID := trimLineTerminator(string(content))
	if err := security.ValidateNodeID(nodeID); err != nil {
		return "", fmt.Errorf("identity file %q: %w", path, err)
	}
	return nodeID, nil
}

// checkIdentityFileMode refuses an identity file that another user can read.
//
// The check is skipped on Windows, where the permission bits Go reports are
// synthesised from the read-only attribute and carry no ownership information. A
// check that cannot answer the question must not pretend to: it would refuse every
// file on one platform and accept every file on the other.
func checkIdentityFileMode(path string) error {
	if runtime.GOOS == "windows" {
		return nil
	}
	info, err := os.Stat(path)
	if err != nil {
		return fmt.Errorf("stat identity file %q: %w", path, err)
	}
	if mode := info.Mode().Perm(); mode&0o077 != 0 {
		return fmt.Errorf("identity file %q has mode %04o, want no group or other access", path, mode)
	}
	return nil
}

// SaveIdentity writes a node id to path with owner-only permissions.
//
// The write is atomic: the content goes to a temporary file in the same directory
// and is renamed over the target. A partial write would leave a file that parses as
// neither the old identifier nor the new one, and the operator would have no way to
// tell which address the Node now answers to.
//
// The temporary file is removed on every failure path, so a failed save does not
// leave a stray file behind.
func SaveIdentity(path string, nodeID string) error {
	if err := security.ValidateNodeID(nodeID); err != nil {
		return err
	}

	directory := filepath.Dir(path)
	temporary, err := os.CreateTemp(directory, ".identity-*")
	if err != nil {
		return fmt.Errorf("create temporary identity file in %q: %w", directory, err)
	}
	temporaryPath := temporary.Name()

	cleanup := func() {
		temporary.Close()
		if err := os.Remove(temporaryPath); err != nil && !errors.Is(err, os.ErrNotExist) {
			fmt.Fprintf(os.Stderr, "remove temporary identity file %q: %v\n", temporaryPath, err)
		}
	}

	if err := temporary.Chmod(identityFileMode); err != nil {
		cleanup()
		return fmt.Errorf("set mode on temporary identity file %q: %w", temporaryPath, err)
	}
	if _, err := temporary.WriteString(nodeID + "\n"); err != nil {
		cleanup()
		return fmt.Errorf("write temporary identity file %q: %w", temporaryPath, err)
	}
	if err := temporary.Sync(); err != nil {
		cleanup()
		return fmt.Errorf("sync temporary identity file %q: %w", temporaryPath, err)
	}
	if err := temporary.Close(); err != nil {
		cleanup()
		return fmt.Errorf("close temporary identity file %q: %w", temporaryPath, err)
	}
	if err := os.Rename(temporaryPath, path); err != nil {
		cleanup()
		return fmt.Errorf("rename temporary identity file over %q: %w", path, err)
	}
	return nil
}

// EnsureIdentity loads the identity file, generating and saving one when it does
// not exist yet.
//
// The generated flag tells the caller whether the identifier is new, so the caller
// can print it once. Printing it on every start would fill a log with an address
// that never changes.
func EnsureIdentity(path string) (nodeID string, generated bool, err error) {
	loaded, err := LoadIdentity(path)
	if err == nil {
		return loaded, false, nil
	}
	if !errors.Is(err, ErrIdentityMissing) {
		return "", false, err
	}

	created, err := security.NewNodeID()
	if err != nil {
		return "", false, err
	}
	if err := SaveIdentity(path, created); err != nil {
		return "", false, err
	}
	return created, true, nil
}

// RegenerateIdentity replaces the identity file with a fresh node id.
//
// Regeneration changes the address, not the credential. The credentials the Node
// accepts live in a separate file, so regenerating the identifier does not revoke a
// caller: an operator who wants to revoke a caller edits the credential file, and an
// operator who wants a new address runs this command. Keeping the two separate is
// what stops a routine address change from locking every caller out.
func RegenerateIdentity(path string) (string, error) {
	created, err := security.NewNodeID()
	if err != nil {
		return "", err
	}
	if err := SaveIdentity(path, created); err != nil {
		return "", err
	}
	return created, nil
}
