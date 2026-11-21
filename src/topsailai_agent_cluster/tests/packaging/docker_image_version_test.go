package packaging_test

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// moduleRootByName walks up from the working directory until it finds the
// go.mod that declares this module, and returns that directory.
//
// The depth is deliberately not counted. A guard that reads "../../Dockerfile"
// is correct only for one directory layout, and it fails in the direction that
// hides itself: adding a directory level usually still resolves to a real file
// one level off, so the read succeeds and the assertion runs against the wrong
// content. Resolving by module identity makes a layout change a non-event.
func moduleRootByName(t *testing.T) string {
	t.Helper()
	dir, err := os.Getwd()
	if err != nil {
		t.Fatalf("cannot read the working directory: %v", err)
	}
	for {
		content, err := os.ReadFile(filepath.Join(dir, "go.mod"))
		if err == nil && strings.Contains(string(content), "module topsailai_agent_cluster") {
			return dir
		}
		parent := filepath.Dir(dir)
		if parent == dir {
			t.Fatalf("cannot locate the module root from %s", dir)
		}
		dir = parent
	}
}

// TestDockerfileInjectsTheVersionIdentity guards the container image against
// shipping a binary that cannot name its own release.
//
// The image is built from a context that carries no .git, so `-buildvcs`
// records nothing and the version variables keep their defaults. Without an
// explicit -X the container answers "0.0.0-unpackaged" to `-v`, which is
// indistinguishable from a local build and tells an operator nothing about what
// the container runs.
//
// The symbol must be named by its full module path. `-X` silently ignores a
// path it cannot resolve: the build succeeds, the exit code is zero, and the
// defaults stay in place. That is why this test asserts the exact symbol rather
// than the presence of an -X flag.
func TestDockerfileInjectsTheVersionIdentity(t *testing.T) {
	root := moduleRootByName(t)
	content, err := os.ReadFile(filepath.Join(root, "docker", "Dockerfile"))
	if err != nil {
		t.Fatalf("cannot read docker/Dockerfile: %v", err)
	}
	dockerfile := string(content)

	for _, symbol := range []string{"Version", "Commit", "BuildTime"} {
		want := "-X topsailai_agent_cluster/internal/version." + symbol + "="
		if !strings.Contains(dockerfile, want) {
			t.Errorf("docker/Dockerfile does not inject %q; a container built from it "+
				"reports the default identity instead of the release it was built from", want)
		}
	}

	// A short symbol path is the specific mistake this guard exists for, so it
	// is rejected explicitly rather than left to the assertion above. Without
	// this check a future edit could add the full path for one variable and a
	// short path for another, and only the first would take effect.
	if strings.Contains(dockerfile, "-X internal/version.") {
		t.Errorf("docker/Dockerfile names a version symbol without its module path; " +
			"-X ignores an unresolvable path and exits zero, so the value would never be set")
	}
}

// TestMakefilePassesTheVersionBuildArguments guards the other half of the same
// contract.
//
// The Dockerfile declares the values as build arguments, so a build that does
// not pass them falls back to the defaults even though the Dockerfile is
// correct. The two halves are separate files, and each one looks complete on its
// own, which is exactly why both need an assertion.
func TestMakefilePassesTheVersionBuildArguments(t *testing.T) {
	root := moduleRootByName(t)
	content, err := os.ReadFile(filepath.Join(root, "Makefile"))
	if err != nil {
		t.Fatalf("cannot read Makefile: %v", err)
	}
	makefile := string(content)

	for _, name := range []string{"VERSION", "COMMIT", "BUILD_TIME"} {
		want := "--build-arg " + name + "=$(" + name + ")"
		if !strings.Contains(makefile, want) {
			t.Errorf("the image-build target does not pass %q; the Dockerfile would fall "+
				"back to its defaults and the image would report no release identity", want)
		}
	}
}
