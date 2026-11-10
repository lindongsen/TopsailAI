package node

import (
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"runtime"

	"topsailai_connector/internal/security"
)

// IdentityFileName is the file inside the config directory that holds the
// node-id.node-token pair.
//
// The pair lives in a file rather than in the environment because the Node
// rewrites it itself when the operator regenerates it, and because a value the
// Node owns belongs in a file the Node owns rather than in the environment of
// whatever process launched it.
const IdentityFileName = "identity"

// identityFileMode is the mode the identity file is created with. It holds a
// credential that never expires, so it is readable by its owner and nobody else.
const identityFileMode = 0o600

// ErrIdentityMissing reports that no identity file exists yet. It is a distinct
// error because the caller's response is different: a missing identity is
// generated, while a malformed identity is a startup failure.
var ErrIdentityMissing = errors.New("node identity file is missing")

// IdentityPath returns the identity file path inside a config directory.
func IdentityPath(configDir string) string {
	return filepath.Join(configDir, IdentityFileName)
}

// LoadIdentity reads the identity file at path.
//
// Every failure is a refusal rather than a repair. A malformed file is not
// regenerated, because regenerating would silently invalidate the pair the
// operator already copied into a CLI, and the operator would see a confusing
// authentication failure instead of the real cause.
func LoadIdentity(path string) (security.NodeIdentity, error) {
	content, err := os.ReadFile(path)
	if err != nil {
		if errors.Is(err, os.ErrNotExist) {
			return security.NodeIdentity{}, fmt.Errorf("%w: %s", ErrIdentityMissing, path)
		}
		return security.NodeIdentity{}, fmt.Errorf("read identity file %q: %w", path, err)
	}

	if err := checkIdentityFileMode(path); err != nil {
		return security.NodeIdentity{}, err
	}

	identity, err := security.ParseNodeIdentity(trimLineTerminator(string(content)))
	if err != nil {
		return security.NodeIdentity{}, fmt.Errorf("identity file %q: %w", path, err)
	}
	return identity, nil
}

// checkIdentityFileMode refuses an identity file that another user can read.
//
// The check is skipped on Windows, where the permission bits Go reports are
// synthesised from the read-only attribute and carry no ownership information. A
// check that cannot answer the question must not pretend to: it would refuse
// every file on one platform and accept every file on the other.
func checkIdentityFileMode(path string) error {
	if runtime.GOOS == "windows" {
		return nil
	}
	info, err := os.Stat(path)
	if err != nil {
		return fmt.Errorf("stat identity file %q: %w", path, err)
	}
	if mode := info.Mode().Perm(); mode&0o077 != 0 {
		return fmt.Errorf("identity file %q has mode %04o, want no group or other access; it holds a credential that never expires", path, mode)
	}
	return nil
}

// SaveIdentity writes an identity to path with owner-only permissions.
//
// The write is atomic: the content goes to a temporary file in the same
// directory and is renamed over the target. A partial write would leave a file
// that parses as neither the old pair nor the new one, and the operator would
// have no way to tell which credential the Node now holds.
//
// The temporary file is removed on every failure path, so a failed save does not
// leave a stray file holding a credential.
func SaveIdentity(path string, identity security.NodeIdentity) error {
	if err := security.ValidateNodeID(identity.ID); err != nil {
		return err
	}
	if err := security.ValidateNodeToken(identity.Token); err != nil {
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
			// A stray temporary file holds a credential, so a failure to remove
			// it is reported rather than swallowed.
			fmt.Fprintf(os.Stderr, "remove temporary identity file %q: %v\n", temporaryPath, err)
		}
	}

	if err := temporary.Chmod(identityFileMode); err != nil {
		cleanup()
		return fmt.Errorf("set mode on temporary identity file %q: %w", temporaryPath, err)
	}
	if _, err := temporary.WriteString(identity.String() + "\n"); err != nil {
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
// The generated flag tells the caller whether the pair is new, so the caller can
// print it once. Printing it on every start would put a credential into a log on
// every start, which is the leak the design forbids.
func EnsureIdentity(path string) (identity security.NodeIdentity, generated bool, err error) {
	loaded, err := LoadIdentity(path)
	if err == nil {
		return loaded, false, nil
	}
	if !errors.Is(err, ErrIdentityMissing) {
		return security.NodeIdentity{}, false, err
	}

	created, err := security.NewNodeIdentity()
	if err != nil {
		return security.NodeIdentity{}, false, err
	}
	if err := SaveIdentity(path, created); err != nil {
		return security.NodeIdentity{}, false, err
	}
	return created, true, nil
}

// RegenerateIdentity replaces the identity file with a fresh pair.
//
// keepID keeps the identifier and replaces only the token, which is what an
// operator needs when the CLI's routing target must stay valid. Both forms
// invalidate the previous token immediately, because the Node compares against
// the value it currently holds and keeps no history: a Node that accepted an old
// token after regeneration would defeat the purpose of regenerating.
func RegenerateIdentity(path string, keepID bool) (security.NodeIdentity, error) {
	var next security.NodeIdentity
	if keepID {
		current, err := LoadIdentity(path)
		if err != nil {
			return security.NodeIdentity{}, err
		}
		regenerated, err := security.NewNodeToken(current.ID)
		if err != nil {
			return security.NodeIdentity{}, err
		}
		next = regenerated
	} else {
		created, err := security.NewNodeIdentity()
		if err != nil {
			return security.NodeIdentity{}, err
		}
		next = created
	}

	if err := SaveIdentity(path, next); err != nil {
		return security.NodeIdentity{}, err
	}
	return next, nil
}
