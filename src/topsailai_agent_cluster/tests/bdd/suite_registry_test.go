package bdd

import (
	"os"
	"path/filepath"
	"sort"
	"testing"
)

// featureDir is the directory that holds every feature file, relative to this
// package directory. It matches the prefix used by featurePaths.
const featureDir = "../../features"

// TestFeatureRegistryHasNoDuplicates fails when the same feature path is listed
// more than once. A duplicate runs the same scenarios twice, which inflates the
// scenario count and hides that coverage did not actually grow.
func TestFeatureRegistryHasNoDuplicates(t *testing.T) {
	seen := make(map[string]int, len(featurePaths))
	for _, path := range featurePaths {
		seen[path]++
	}

	var duplicates []string
	for path, count := range seen {
		if count > 1 {
			duplicates = append(duplicates, path)
		}
	}
	sort.Strings(duplicates)

	if len(duplicates) > 0 {
		t.Fatalf("feature registry lists %d path(s) more than once: %v", len(duplicates), duplicates)
	}
}

// TestFeatureRegistryPathsExist fails when a registered path does not resolve to
// a file. A stale entry makes the suite fail loudly, which is the intended
// behaviour, but this guard reports it as a registry defect instead.
func TestFeatureRegistryPathsExist(t *testing.T) {
	for _, path := range featurePaths {
		info, err := os.Stat(path)
		if err != nil {
			t.Errorf("registered feature path %q does not exist: %v", path, err)
			continue
		}
		if info.IsDir() {
			t.Errorf("registered feature path %q is a directory, not a file", path)
		}
	}
}

// TestFeatureRegistryCoversEveryFeatureFile fails when a feature file on disk is
// not registered. This is the silent-loss case: the scenarios in that file stop
// running while the suite still reports success.
func TestFeatureRegistryCoversEveryFeatureFile(t *testing.T) {
	onDisk, err := filepath.Glob(filepath.Join(featureDir, "*.feature"))
	if err != nil {
		t.Fatalf("glob %s: %v", featureDir, err)
	}
	if len(onDisk) == 0 {
		t.Fatalf("no feature files found under %s; the guard cannot verify anything", featureDir)
	}

	registered := make(map[string]struct{}, len(featurePaths))
	for _, path := range featurePaths {
		registered[filepath.Clean(path)] = struct{}{}
	}

	var missing []string
	for _, path := range onDisk {
		if _, ok := registered[filepath.Clean(path)]; !ok {
			missing = append(missing, path)
		}
	}
	sort.Strings(missing)

	if len(missing) > 0 {
		t.Fatalf("%d feature file(s) exist on disk but are not registered, so their scenarios never run: %v", len(missing), missing)
	}
}

// TestFeatureRegistryCountMatchesDisk fails when the registry and the directory
// disagree on how many feature files exist. It is a coarse backstop for the two
// precise checks above, and it catches a registry that lists a file twice while
// omitting another, which keeps the total unchanged.
func TestFeatureRegistryCountMatchesDisk(t *testing.T) {
	onDisk, err := filepath.Glob(filepath.Join(featureDir, "*.feature"))
	if err != nil {
		t.Fatalf("glob %s: %v", featureDir, err)
	}

	if len(featurePaths) != len(onDisk) {
		t.Fatalf("feature registry has %d entries but %d feature file(s) exist on disk", len(featurePaths), len(onDisk))
	}
}
