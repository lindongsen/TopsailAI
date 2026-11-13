//go:build bdd

package bdd

import (
	"os"
	"path/filepath"
	"testing"

	"topsailai_connector/internal/node"
	"topsailai_connector/internal/security"
)

// world is the state one scenario builds up. Every scenario gets a fresh world,
// so a scenario cannot pass because of what an earlier one left behind.
type world struct {
	baseDir    string
	configDir  string
	scopeDir   string
	policyPath string
	authority  *node.Authority
	identity   security.NodeIdentity
	lastError  error
	lastCode   string
	lastData   []byte
	lastList   []node.Entry
	lastEntry  node.Entry
}

// newWorld creates an empty world rooted in a temporary directory.
func newWorld(t *testing.T) *world {
	t.Helper()
	base := t.TempDir()
	state := &world{
		baseDir:    base,
		configDir:  filepath.Join(base, "config"),
		scopeDir:   filepath.Join(base, "project"),
		policyPath: filepath.Join(base, "config", "policy.yaml"),
	}
	if err := os.MkdirAll(state.configDir, 0o700); err != nil {
		t.Fatalf("create config directory: %v", err)
	}
	if err := os.MkdirAll(state.scopeDir, 0o755); err != nil {
		t.Fatalf("create scope directory: %v", err)
	}
	return state
}

// writePolicy writes a policy document to the world's policy path.
func (w *world) writePolicy(document string) error {
	return os.WriteFile(w.policyPath, []byte(document), 0o600)
}

// writeScopeFile writes a file inside the scope directory.
func (w *world) writeScopeFile(name string, content string) error {
	return os.WriteFile(filepath.Join(w.scopeDir, name), []byte(content), 0o644)
}

// loadAuthority loads the policy and opens every scope it defines.
func (w *world) loadAuthority() error {
	authority, err := node.LoadAuthority(w.policyPath, nil, "")
	if err != nil {
		return err
	}
	w.authority = authority
	return nil
}

// close releases the authority if one was opened.
func (w *world) close() {
	if w.authority != nil {
		w.authority.Close()
	}
}
