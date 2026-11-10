//go:build bdd

package bdd

import (
	"path/filepath"
	"testing"
)

// TestFeatures runs every feature file in features/ against the step registry.
//
// Each scenario gets a fresh world, so a scenario cannot pass because of what an
// earlier one left behind. The world is closed after the scenario, which releases
// the scope handles; on Windows an unclosed handle keeps a directory from being
// removed.
func TestFeatures(t *testing.T) {
	registered := steps()
	for _, path := range featureFiles(t, "features") {
		path := path
		t.Run(filepath.Base(path), func(t *testing.T) {
			runFeature(t, path, registered, func(t *testing.T) *world {
				state := newWorld(t)
				t.Cleanup(state.close)
				return state
			})
		})
	}
}
