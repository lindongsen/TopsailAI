package version

import (
	"encoding/json"
	"strings"
	"testing"

	"gopkg.in/yaml.v3"
)

// setBuildMetadata overrides the link-time variables for one test and restores
// them afterwards, so tests do not leak state into each other.
func setBuildMetadata(t *testing.T, version, commit, buildDate string) {
	t.Helper()
	oldVersion, oldCommit, oldBuildDate := Version, Commit, BuildDate
	Version, Commit, BuildDate = version, commit, buildDate
	t.Cleanup(func() {
		Version, Commit, BuildDate = oldVersion, oldCommit, oldBuildDate
	})
}

func TestGetFallsBackToDevelopmentMarkers(t *testing.T) {
	setBuildMetadata(t, "", "", "")

	got := Get()
	if got.Version != DevelopmentVersion {
		t.Fatalf("Version = %q, want %q", got.Version, DevelopmentVersion)
	}
	if got.Commit != UnknownCommit {
		t.Fatalf("Commit = %q, want %q", got.Commit, UnknownCommit)
	}
	if got.BuildDate != UnknownBuildDate {
		t.Fatalf("BuildDate = %q, want %q", got.BuildDate, UnknownBuildDate)
	}
}

func TestGetReturnsInjectedMetadata(t *testing.T) {
	setBuildMetadata(t, "v1.2.3", "abc1234", "2026-11-22T03:10:23Z")

	got := Get()
	if got.Version != "v1.2.3" {
		t.Fatalf("Version = %q, want v1.2.3", got.Version)
	}
	if got.Commit != "abc1234" {
		t.Fatalf("Commit = %q, want abc1234", got.Commit)
	}
	if got.BuildDate != "2026-11-22T03:10:23Z" {
		t.Fatalf("BuildDate = %q, want 2026-11-22T03:10:23Z", got.BuildDate)
	}
}

func TestGetFillsOnlyMissingFields(t *testing.T) {
	setBuildMetadata(t, "v0.9.0", "", "")

	got := Get()
	if got.Version != "v0.9.0" {
		t.Fatalf("Version = %q, want v0.9.0", got.Version)
	}
	if got.Commit != UnknownCommit {
		t.Fatalf("Commit = %q, want %q", got.Commit, UnknownCommit)
	}
	if got.BuildDate != UnknownBuildDate {
		t.Fatalf("BuildDate = %q, want %q", got.BuildDate, UnknownBuildDate)
	}
}

func TestLineIncludesBuildDateWhenKnown(t *testing.T) {
	setBuildMetadata(t, "v1.2.3", "abc1234", "2026-11-22T03:10:23Z")

	got := Get().Line()
	want := "topsailai-data v1.2.3 (commit abc1234, built 2026-11-22T03:10:23Z)"
	if got != want {
		t.Fatalf("Line() = %q, want %q", got, want)
	}
}

func TestLineOmitsUnknownBuildDate(t *testing.T) {
	setBuildMetadata(t, "", "", "")

	got := Get().Line()
	want := "topsailai-data dev (commit unknown)"
	if got != want {
		t.Fatalf("Line() = %q, want %q", got, want)
	}
	if strings.Contains(got, "built ") {
		t.Fatalf("Line() should omit an unknown build date, got %q", got)
	}
}

func TestInfoSerializesWithStableKeys(t *testing.T) {
	setBuildMetadata(t, "v1.2.3", "abc1234", "2026-11-22T03:10:23Z")
	info := Get()

	jsonData, err := json.Marshal(info)
	if err != nil {
		t.Fatalf("marshal json: %v", err)
	}
	for _, key := range []string{`"version"`, `"commit"`, `"build_date"`} {
		if !strings.Contains(string(jsonData), key) {
			t.Fatalf("json output missing %s: %s", key, jsonData)
		}
	}

	yamlData, err := yaml.Marshal(info)
	if err != nil {
		t.Fatalf("marshal yaml: %v", err)
	}
	for _, key := range []string{"version:", "commit:", "build_date:"} {
		if !strings.Contains(string(yamlData), key) {
			t.Fatalf("yaml output missing %s: %s", key, yamlData)
		}
	}
}
