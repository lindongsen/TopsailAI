package bdd

import (
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"
)

// groupEnv selects one named feature group for this test process.
//
// Go's -timeout is a budget for the whole test binary, so a group only gets its
// own budget and its own report when it runs in its own process. The Makefile
// therefore runs one `go test` per group and passes the group name here.
const groupEnv = "AGENT_CLUSTER_BDD_GROUP"

// featuresEnv selects an explicit comma-separated list of feature basenames.
//
// It exists for two reasons that a named group cannot serve: measuring one
// feature at a time while the groups are being balanced, and debugging a single
// feature without running its whole group. It is test-only configuration and is
// never read by production code.
const featuresEnv = "AGENT_CLUSTER_BDD_FEATURES"

// featureGroups partitions the suite into bounded groups, keyed by group name.
//
// Each entry lists feature basenames without the directory or the .feature
// suffix. Basenames are used instead of full paths so a typo cannot silently
// point at a file outside the registry: suite_groups_test.go resolves every
// basename against featurePaths and fails when one does not match.
//
// The partition is deliberately explicit rather than derived from a directory
// pattern. A new feature file must be assigned to a group on purpose, because an
// unassigned file would otherwise stop running while the suite still reported
// success.
//
// The split follows measured per-feature duration, not topic alone. Measured on
// 2026-11-18 with AGENT_CLUSTER_BDD_FEATURES selecting one feature per process,
// the whole registry cost 352.9s, and two features dominated it:
// endpoint_server_rehome_receipts at 130.2s and endpoint_server_rehome_fallback
// at 96.6s. Keeping them in one group would reproduce the original defect, where
// a single group's duration decides whether the whole run reports at all. They
// are therefore separate groups, and the remaining re-home features form a third.
var featureGroups = map[string][]string{
	// The two longest features each get their own group so neither can consume
	// another feature's budget or discard its results.
	"rehome-receipts": {
		"endpoint_server_rehome_receipts",
	},
	"rehome-fallback": {
		"endpoint_server_rehome_fallback",
	},
	// The remaining re-home features cover connection establishment and the
	// deployment shape, which are cheap because they do not drive repeated
	// receipt settlement.
	"rehome": {
		"endpoint_server_rehome_connection",
		"endpoint_server_rehome_deployment",
	},
	// The policy group exercises the Endpoint access-policy directory and the
	// per-operation permission matrices.
	"policy": {
		"endpoint_access_policy",
		"endpoint_permission_matrix",
		"endpoint_query_permission_matrix",
	},
	// The lifecycle group covers inventory reporting, expiry and the command
	// journal, all of which drive real processes through the HTTP boundary.
	"lifecycle": {
		"inventory",
		"endpoint_expiry",
		"command_idempotency",
		"command_recovery",
		"commands",
		"cancellation",
		"timeouts",
	},
	// The surface group covers the operator CLI and TUI rendering paths.
	"surface": {
		"tui",
		"output_follow",
		"output_scope",
		"messages",
		"model_command",
		"unknown_input_offer",
		"notifications",
		"capability",
		"provider_response",
		"lifecycle",
		"real_boundary",
		"bidirectional_channel",
	},
}

// groupOrder is the order the Makefile runs the groups in.
//
// It is a separate value from the map so the run order is deterministic and
// reviewable; a map iteration order would change the report order between runs.
// The longest groups run first so a failure in them is reported as early as
// possible instead of after every cheap group has already passed.
var groupOrder = []string{"rehome-receipts", "rehome-fallback", "rehome", "policy", "lifecycle", "surface"}

// selectedFeaturePaths returns the feature paths this test process must run.
//
// An empty environment selects every registered feature, which keeps a plain
// `go test ./tests/bdd` equivalent to the full suite. A named group selects that
// group, and an explicit list selects exactly those features. Setting both is
// rejected rather than resolved by precedence, because two selectors that
// disagree would silently run a subset the caller did not ask for.
func selectedFeaturePaths() ([]string, error) {
	group := strings.TrimSpace(os.Getenv(groupEnv))
	explicit := strings.TrimSpace(os.Getenv(featuresEnv))

	if group != "" && explicit != "" {
		return nil, fmt.Errorf("%s and %s are both set; set only one so the selected subset is unambiguous", groupEnv, featuresEnv)
	}
	if group != "" {
		return pathsForGroup(group)
	}
	if explicit != "" {
		return pathsForFeatures(explicit)
	}
	return append([]string(nil), featurePaths...), nil
}

// pathsForGroup resolves one named group to its registered feature paths.
func pathsForGroup(name string) ([]string, error) {
	basenames, ok := featureGroups[name]
	if !ok {
		return nil, fmt.Errorf("unknown BDD group %q; known groups are %v", name, groupOrder)
	}
	return resolveBasenames(basenames)
}

// pathsForFeatures resolves a comma-separated basename list to registered paths.
func pathsForFeatures(list string) ([]string, error) {
	parts := strings.Split(list, ",")
	basenames := make([]string, 0, len(parts))
	for _, part := range parts {
		trimmed := strings.TrimSpace(part)
		if trimmed == "" {
			return nil, fmt.Errorf("%s contains an empty entry: %q", featuresEnv, list)
		}
		basenames = append(basenames, trimmed)
	}
	return resolveBasenames(basenames)
}

// resolveBasenames maps feature basenames onto the paths in featurePaths.
//
// Resolution goes through featurePaths rather than building a path from the
// basename, so a selector can only ever run a feature the registry already
// covers. A basename that is not registered is an error instead of a path that
// happens to exist on disk.
func resolveBasenames(basenames []string) ([]string, error) {
	byBase := make(map[string]string, len(featurePaths))
	for _, path := range featurePaths {
		base := strings.TrimSuffix(filepath.Base(path), ".feature")
		byBase[base] = path
	}

	paths := make([]string, 0, len(basenames))
	seen := make(map[string]struct{}, len(basenames))
	for _, base := range basenames {
		path, ok := byBase[base]
		if !ok {
			return nil, fmt.Errorf("feature %q is not registered in featurePaths; registered features are %v", base, sortedFeatureBasenames(byBase))
		}
		if _, duplicate := seen[base]; duplicate {
			return nil, fmt.Errorf("feature %q is selected more than once", base)
		}
		seen[base] = struct{}{}
		paths = append(paths, path)
	}
	return paths, nil
}

// sortedFeatureBasenames returns the registered basenames in sorted order for a
// stable error message.
func sortedFeatureBasenames(byBase map[string]string) []string {
	names := make([]string, 0, len(byBase))
	for base := range byBase {
		names = append(names, base)
	}
	sort.Strings(names)
	return names
}
