package node

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"topsailai_connector/internal/protocol"
)

// deepPath builds a relative path of `depth` components named "d" followed by
// the file name.
func deepPath(depth int, name string) string {
	return strings.Repeat("d/", depth) + name
}

// makeDeepTree creates `depth` nested directories under root and writes one file
// at the bottom. It reports false when the platform refuses to create the tree,
// which is a filesystem limit rather than a fence defect.
func makeDeepTree(t *testing.T, root string, depth int, payload string) bool {
	t.Helper()

	abs := filepath.Join(root, filepath.FromSlash(strings.Repeat("d/", depth)))
	if err := os.MkdirAll(abs, 0o755); err != nil {
		return false
	}
	if err := os.WriteFile(filepath.Join(abs, "f.txt"), []byte(payload), 0o644); err != nil {
		return false
	}
	return true
}

// TestScopeReadDeeplyNestedPath checks that depth is not silently limited.
//
// The existing nested test reads one level, which proves almost nothing: a fence
// that only handled the root's immediate children would pass it. Depth is the
// dimension a caller actually uses, because a real project tree is many levels
// deep, so a limit here would be a limit on the product rather than on an attack.
//
// The payload is asserted at every depth, so a successful open that returned the
// wrong bytes is a failure rather than a pass.
func TestScopeReadDeeplyNestedPath(t *testing.T) {
	root, _ := newScopeFixture(t)
	scope := openFixtureScope(t, root)

	// Depths up to 10 must work on every supported platform, so a failure there
	// is a defect. Deeper trees are skipped when the platform refuses to create
	// them, because a filesystem limit is not a fence defect and reporting it as
	// one would train a reader to ignore this test.
	for _, depth := range []int{1, 2, 3, 10, 100, 500} {
		t.Run(fmt.Sprintf("depth-%d", depth), func(t *testing.T) {
			payload := fmt.Sprintf("payload-at-%d", depth)
			if !makeDeepTree(t, root, depth, payload) {
				if depth <= 10 {
					t.Fatalf("depth %d: the platform refused a shallow tree", depth)
				}
				t.Skipf("depth %d: the platform refused to create the tree", depth)
			}

			fileRel := deepPath(depth, "f.txt")

			data, truncated, err := scope.Read(fileRel, 0, 0)
			if err != nil {
				t.Fatalf("Read(%d levels) = %v, want nil", depth, err)
			}
			if string(data) != payload {
				t.Fatalf("Read(%d levels) = %q, want %q", depth, data, payload)
			}
			if truncated {
				t.Fatalf("Read(%d levels) reported truncation for a small file", depth)
			}

			entry, err := scope.Stat(fileRel)
			if err != nil {
				t.Fatalf("Stat(%d levels) = %v, want nil", depth, err)
			}
			if entry.Type != "file" {
				t.Fatalf("Stat(%d levels) type = %q, want file", depth, entry.Type)
			}
			if entry.Size != int64(len(payload)) {
				t.Fatalf("Stat(%d levels) size = %d, want %d", depth, entry.Size, len(payload))
			}

			entries, err := scope.List(strings.TrimSuffix(deepPath(depth, ""), "/"))
			if err != nil {
				t.Fatalf("List(%d levels) = %v, want nil", depth, err)
			}
			if len(entries) != 1 || entries[0].Name != "f.txt" {
				t.Fatalf("List(%d levels) = %v, want exactly [f.txt]", depth, entryNames(entries))
			}
		})
	}
}

// TestScopeDeepPathStillRefusesEscape checks that depth does not weaken the
// fence. A symlink planted at the bottom of a deep tree is the case a
// depth-limited or depth-truncating implementation would miss, because the
// escape happens far from the root where a shallow check never looks.
func TestScopeDeepPathStillRefusesEscape(t *testing.T) {
	root, outside := newScopeFixture(t)
	scope := openFixtureScope(t, root)

	const depth = 20
	if !makeDeepTree(t, root, depth, "deep payload") {
		t.Skipf("the platform refused to create a %d level tree", depth)
	}

	linkRel := deepPath(depth, "escape")
	linkAbs := filepath.Join(root, filepath.FromSlash(linkRel))
	mustSymlink(t, outside, linkAbs)

	if _, _, err := scope.Read(linkRel+"/secret.txt", 0, 0); CodeOf(err) != protocol.CodeDenied {
		t.Fatalf("Read through a deep escaping symlink = %v, want denied", err)
	}

	// Stat must report the link itself without following it, at any depth.
	entry, err := scope.Stat(linkRel)
	if err != nil {
		t.Fatalf("Stat(deep symlink) = %v, want nil", err)
	}
	if !entry.IsSymlink {
		t.Fatalf("Stat(deep symlink) reported type %q, want a symlink", entry.Type)
	}
}

// TestScopeRejectsPathOverTheGrammarLimit checks the boundary the grammar owns.
// A path longer than MaxPathLength is refused before it reaches the filesystem,
// so the refusal does not depend on the kernel's own limit.
func TestScopeRejectsPathOverTheGrammarLimit(t *testing.T) {
	root, _ := newScopeFixture(t)
	scope := openFixtureScope(t, root)

	overLong := strings.Repeat("a", MaxPathLength+1)

	if _, _, err := scope.Read(overLong, 0, 0); CodeOf(err) != protocol.CodeInvalidArgument {
		t.Fatalf("Read(over-long path) = %v, want invalid_argument", err)
	}
	if _, err := scope.Stat(overLong); CodeOf(err) != protocol.CodeInvalidArgument {
		t.Fatalf("Stat(over-long path) = %v, want invalid_argument", err)
	}
	if _, err := scope.List(overLong); CodeOf(err) != protocol.CodeInvalidArgument {
		t.Fatalf("List(over-long path) = %v, want invalid_argument", err)
	}
}

// TestScopeRefusesPathAtTheFilesystemLimit checks the seam between the grammar
// limit and the filesystem limit.
//
// A path the grammar accepts can still be refused by the kernel, because
// MaxPathLength and PATH_MAX are the same order of magnitude. The security
// property is that such a path never succeeds: whether the refusal is reported as
// not_found or denied is a classification detail, but a success would mean the
// fence opened something it could not fully resolve.
func TestScopeRefusesPathAtTheFilesystemLimit(t *testing.T) {
	root, _ := newScopeFixture(t)
	scope := openFixtureScope(t, root)

	// A path just under MaxPathLength passes the grammar and cannot exist on
	// disk, because the kernel's own limit counts the absolute path.
	atLimit := strings.Repeat("d/", (MaxPathLength-5)/2) + "f.txt"
	if len(atLimit) > MaxPathLength {
		t.Fatalf("fixture path is %d bytes, over the grammar limit", len(atLimit))
	}

	data, _, err := scope.Read(atLimit, 0, 0)
	if err == nil {
		t.Fatalf("Read(path at the filesystem limit) succeeded with %d bytes, want a refusal", len(data))
	}
	switch CodeOf(err) {
	case protocol.CodeNotFound, protocol.CodeDenied, protocol.CodeInvalidArgument:
	default:
		t.Fatalf("Read(path at the filesystem limit) = %v, want not_found, denied or invalid_argument", err)
	}
}
