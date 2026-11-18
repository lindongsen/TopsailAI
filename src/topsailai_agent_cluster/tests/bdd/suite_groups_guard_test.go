package bdd

import (
	"path/filepath"
	"sort"
	"strings"
	"testing"
)

// TestFeatureGroupsPartitionTheRegistry fails when the groups do not cover every
// registered feature exactly once.
//
// This is the silent-loss guard for the grouped runner. A feature that belongs to
// no group stops running while every group still reports success, and a feature
// that belongs to two groups runs twice, which inflates the scenario count and
// hides that coverage did not grow. Neither failure is visible in a green run.
func TestFeatureGroupsPartitionTheRegistry(t *testing.T) {
	registered := make(map[string]struct{}, len(featurePaths))
	for _, path := range featurePaths {
		registered[strings.TrimSuffix(filepath.Base(path), ".feature")] = struct{}{}
	}

	assigned := make(map[string][]string, len(registered))
	for group, basenames := range featureGroups {
		for _, base := range basenames {
			assigned[base] = append(assigned[base], group)
		}
	}

	var unassigned []string
	for base := range registered {
		if len(assigned[base]) == 0 {
			unassigned = append(unassigned, base)
		}
	}
	sort.Strings(unassigned)
	if len(unassigned) > 0 {
		t.Fatalf("%d registered feature(s) belong to no group, so their scenarios never run: %v", len(unassigned), unassigned)
	}

	var duplicated []string
	for base, groups := range assigned {
		if len(groups) > 1 {
			sort.Strings(groups)
			duplicated = append(duplicated, base+" in "+strings.Join(groups, "+"))
		}
	}
	sort.Strings(duplicated)
	if len(duplicated) > 0 {
		t.Fatalf("%d feature(s) belong to more than one group, so they run twice: %v", len(duplicated), duplicated)
	}

	var unknown []string
	for base := range assigned {
		if _, ok := registered[base]; !ok {
			unknown = append(unknown, base)
		}
	}
	sort.Strings(unknown)
	if len(unknown) > 0 {
		t.Fatalf("%d group entry/entries name a feature that is not registered, so the group cannot run it: %v", len(unknown), unknown)
	}
}

// TestFeatureGroupOrderCoversEveryGroup fails when groupOrder and featureGroups
// disagree.
//
// The Makefile iterates groupOrder, so a group that exists only in the map is
// never run, and a name that exists only in groupOrder makes the runner fail on
// an unknown group. Both are configuration defects rather than test failures, so
// they are reported here instead of at run time.
func TestFeatureGroupOrderCoversEveryGroup(t *testing.T) {
	inOrder := make(map[string]struct{}, len(groupOrder))
	for _, name := range groupOrder {
		if _, duplicate := inOrder[name]; duplicate {
			t.Fatalf("groupOrder lists %q more than once", name)
		}
		inOrder[name] = struct{}{}
		if _, ok := featureGroups[name]; !ok {
			t.Fatalf("groupOrder names %q but featureGroups has no such group", name)
		}
	}

	var missing []string
	for name := range featureGroups {
		if _, ok := inOrder[name]; !ok {
			missing = append(missing, name)
		}
	}
	sort.Strings(missing)
	if len(missing) > 0 {
		t.Fatalf("%d group(s) exist but are absent from groupOrder, so the runner never runs them: %v", len(missing), missing)
	}
}

// TestSelectedFeaturePathsDefaultsToTheWholeRegistry fails when an unset
// environment selects a subset.
//
// A plain `go test ./tests/bdd` must stay equivalent to the full suite. If the
// default narrowed, a developer running the package directly would verify less
// than the Makefile target while seeing the same green result.
func TestSelectedFeaturePathsDefaultsToTheWholeRegistry(t *testing.T) {
	t.Setenv(groupEnv, "")
	t.Setenv(featuresEnv, "")

	paths, err := selectedFeaturePaths()
	if err != nil {
		t.Fatalf("select with no environment: %v", err)
	}
	if len(paths) != len(featurePaths) {
		t.Fatalf("default selection returned %d path(s), want all %d registered features", len(paths), len(featurePaths))
	}
	for i, path := range paths {
		if path != featurePaths[i] {
			t.Fatalf("default selection path %d = %q, want %q in registry order", i, path, featurePaths[i])
		}
	}
}

// TestSelectedFeaturePathsRejectsTwoSelectors fails when both selectors are set.
//
// Resolving the conflict by precedence would run a subset the caller did not ask
// for, and the caller would have no way to notice: both selectors are valid on
// their own, so the run looks intentional.
func TestSelectedFeaturePathsRejectsTwoSelectors(t *testing.T) {
	t.Setenv(groupEnv, "cluster")
	t.Setenv(featuresEnv, "inventory")

	if _, err := selectedFeaturePaths(); err == nil {
		t.Fatal("two selectors were accepted; want an error so the subset is unambiguous")
	}
}

// TestSelectedFeaturePathsResolvesAGroup fails when a group does not resolve to
// its registered paths.
func TestSelectedFeaturePathsResolvesAGroup(t *testing.T) {
	t.Setenv(groupEnv, "policy")
	t.Setenv(featuresEnv, "")

	paths, err := selectedFeaturePaths()
	if err != nil {
		t.Fatalf("select group policy: %v", err)
	}
	want := featureGroups["policy"]
	if len(paths) != len(want) {
		t.Fatalf("group policy resolved to %d path(s), want %d", len(paths), len(want))
	}
	for i, base := range want {
		if got := strings.TrimSuffix(filepath.Base(paths[i]), ".feature"); got != base {
			t.Fatalf("group policy path %d = %q, want feature %q", i, got, base)
		}
	}
}

// TestSelectedFeaturePathsRejectsAnUnknownFeature fails when a selector names a
// feature the registry does not cover.
//
// Building a path from the basename would let a selector run a file that exists
// on disk but is not registered, which is exactly the state the registry guards
// exist to prevent.
func TestSelectedFeaturePathsRejectsAnUnknownFeature(t *testing.T) {
	t.Setenv(groupEnv, "")
	t.Setenv(featuresEnv, "not_a_registered_feature")

	if _, err := selectedFeaturePaths(); err == nil {
		t.Fatal("an unregistered feature was accepted; want an error so a selector cannot bypass the registry")
	}
}

// TestSelectedFeaturePathsRejectsAnEmptyEntry fails when the explicit list has a
// blank entry.
//
// A trailing comma is the common way to produce one, and silently dropping it
// would run fewer features than the caller listed.
func TestSelectedFeaturePathsRejectsAnEmptyEntry(t *testing.T) {
	t.Setenv(groupEnv, "")
	t.Setenv(featuresEnv, "inventory,")

	if _, err := selectedFeaturePaths(); err == nil {
		t.Fatal("a blank entry was accepted; want an error so the selected list is exactly what was asked for")
	}
}
