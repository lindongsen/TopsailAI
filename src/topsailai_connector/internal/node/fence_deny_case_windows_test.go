//go:build windows

package node

import (
	"os"
	"path/filepath"
	"testing"

	"topsailai_connector/internal/protocol"
)

// TestDenyListRefusesACaseVariedPathOnWindows checks that a deny-listed directory
// is refused when the caller spells it in a different case.
//
// Windows compares paths case-insensitively, so `CONFIG` and `config` are the same
// directory. The deny list is compared against the path the caller wrote, before
// the open, so a case-sensitive comparison would let a caller reach a file inside
// the config directory by changing the spelling. The identity comparison cannot
// cover that case: a file inside the directory is a different inode from the
// directory itself, so only the prefix rule refuses it.
func TestDenyListRefusesACaseVariedPathOnWindows(t *testing.T) {
	base := t.TempDir()
	configDir := filepath.Join(base, "node", "config")
	if err := os.MkdirAll(configDir, 0o700); err != nil {
		t.Fatalf("mkdir config: %v", err)
	}
	writeFile(t, filepath.Join(configDir, "identity"), "node_secret.token_secret")

	// A file inside the config directory that is not itself on the deny list.
	// The identity comparison cannot refuse it, so the prefix rule must.
	nested := filepath.Join(configDir, "nested")
	if err := os.Mkdir(nested, 0o700); err != nil {
		t.Fatalf("mkdir nested: %v", err)
	}
	writeFile(t, filepath.Join(nested, "secret.txt"), "nested secret")

	root := filesystemRootPath(t)
	scope, err := openScope("whole", root, []string{configDir}, configDir, true)
	if err != nil {
		t.Fatalf("openScope(opt-in) = %v, want nil", err)
	}
	defer scope.Close()

	relativeConfig := relativeToRoot(t, configDir)

	spellings := []string{
		relativeConfig,
		upperFirst(relativeConfig),
		toUpper(relativeConfig),
	}

	for _, spelling := range spellings {
		t.Run(spelling, func(t *testing.T) {
			if !scope.isDeniedPath(spelling) {
				t.Fatalf("isDeniedPath(%q) = false, want true because Windows compares case-insensitively", spelling)
			}
			if _, _, err := scope.Read(spelling+"/nested/secret.txt", 0, 0); CodeOf(err) != protocol.CodeDenied {
				t.Fatalf("Read(%q) = %v, want denied", spelling+"/nested/secret.txt", err)
			}
			if _, err := scope.List(spelling); CodeOf(err) != protocol.CodeDenied {
				t.Fatalf("List(%q) = %v, want denied", spelling, err)
			}
		})
	}
}

// upperFirst returns the path with its first letter upper-cased, which is the
// smallest spelling change a caller would try.
func upperFirst(path string) string {
	if path == "" {
		return path
	}
	first := path[0]
	if first >= 'a' && first <= 'z' {
		first = first - 'a' + 'A'
	}
	return string(first) + path[1:]
}

// toUpper returns the path with every ASCII letter upper-cased.
func toUpper(path string) string {
	out := make([]byte, len(path))
	for index := 0; index < len(path); index++ {
		character := path[index]
		if character >= 'a' && character <= 'z' {
			character = character - 'a' + 'A'
		}
		out[index] = character
	}
	return string(out)
}
