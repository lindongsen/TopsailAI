//go:build windows

package node

import (
	"path/filepath"
	"testing"
)

// TestOverlapsConfigDirComparesCaseInsensitivelyOnWindows checks that a scope
// spelled with a different case is still recognised as the config directory.
//
// Windows compares paths case-insensitively, so `C:\Node\CONFIG` and
// `C:\Node\config` are the same directory. A case-sensitive comparison would let
// a scope reach the Node's credential files by changing the spelling, which is
// the same bypass the deny list refuses.
func TestOverlapsConfigDirComparesCaseInsensitivelyOnWindows(t *testing.T) {
	configDir := filepath.Join("C:"+string(filepath.Separator), "Node", "config")

	spellings := []string{
		filepath.Join("C:"+string(filepath.Separator), "Node", "CONFIG"),
		filepath.Join("C:"+string(filepath.Separator), "NODE", "Config"),
		filepath.Join("c:"+string(filepath.Separator), "node", "config"),
	}

	for _, spelling := range spellings {
		if !overlapsConfigDir(spelling, configDir) {
			t.Fatalf("overlapsConfigDir(%q, %q) = false, want true because Windows compares case-insensitively", spelling, configDir)
		}
	}
}

// TestOverlapsConfigDirRefusesAContainingScopeOnWindows checks the containment
// direction on a Windows path, where the volume name is part of the path.
func TestOverlapsConfigDirRefusesAContainingScopeOnWindows(t *testing.T) {
	configDir := filepath.Join("C:"+string(filepath.Separator), "Node", "config")
	containing := filepath.Join("C:"+string(filepath.Separator), "Node")

	if !overlapsConfigDir(containing, configDir) {
		t.Fatalf("overlapsConfigDir(%q, %q) = false, want true for a scope containing the config directory", containing, configDir)
	}
}

// TestOverlapsConfigDirAcceptsADifferentVolumeOnWindows checks that a scope on
// another volume is not treated as overlapping.
//
// filepath.Rel cannot compute a relative path across volumes, so the containment
// test must answer false rather than guess. A guess would refuse a legitimate
// scope on a second drive.
func TestOverlapsConfigDirAcceptsADifferentVolumeOnWindows(t *testing.T) {
	configDir := filepath.Join("C:"+string(filepath.Separator), "Node", "config")
	otherVolume := filepath.Join("D:"+string(filepath.Separator), "Node", "config")

	if overlapsConfigDir(otherVolume, configDir) {
		t.Fatalf("overlapsConfigDir(%q, %q) = true, want false for a scope on another volume", otherVolume, configDir)
	}
}
