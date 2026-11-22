// Package version reports the build metadata of the topsailai-data CLI.
//
// The values are injected at build time through the linker, so the binary
// carries the version of the source it was compiled from instead of a
// hand-maintained constant. A plain `go build` leaves the variables empty and
// the package falls back to development markers, so a version query always
// answers successfully.
package version

import "fmt"

const (
	// Name is the program name reported by a version query.
	Name = "topsailai-data"

	// DevelopmentVersion is reported when no version was injected at build time.
	DevelopmentVersion = "dev"

	// UnknownCommit is reported when no commit was injected at build time.
	UnknownCommit = "unknown"

	// UnknownBuildDate is reported when no build date was injected at build time.
	UnknownBuildDate = "unknown"
)

// Build metadata injected through `-ldflags -X`. The values stay empty for a
// plain `go build`, which is why every reader goes through Get.
var (
	// Version is the release version, normally a git tag such as v1.2.3.
	Version = ""

	// Commit is the git commit the binary was built from.
	Commit = ""

	// BuildDate is the UTC build timestamp in RFC3339 format.
	BuildDate = ""
)

// Info holds the resolved build metadata of the running binary.
type Info struct {
	// Version is the release version or the development marker.
	Version string `json:"version" yaml:"version"`

	// Commit is the git commit or the unknown marker.
	Commit string `json:"commit" yaml:"commit"`

	// BuildDate is the build timestamp or the unknown marker.
	BuildDate string `json:"build_date" yaml:"build_date"`
}

// Get returns the build metadata of the running binary, substituting
// development markers for values that were not injected at build time.
func Get() Info {
	return Info{
		Version:   valueOr(Version, DevelopmentVersion),
		Commit:    valueOr(Commit, UnknownCommit),
		BuildDate: valueOr(BuildDate, UnknownBuildDate),
	}
}

// Line renders the metadata as one human-readable line. The build date is
// omitted when it is unknown so the line stays short for development builds.
func (i Info) Line() string {
	line := fmt.Sprintf("%s %s (commit %s", Name, i.Version, i.Commit)
	if i.BuildDate != UnknownBuildDate {
		line += ", built " + i.BuildDate
	}
	return line + ")"
}

// valueOr returns value when it is non-empty, otherwise fallback.
func valueOr(value, fallback string) string {
	if value == "" {
		return fallback
	}
	return value
}
