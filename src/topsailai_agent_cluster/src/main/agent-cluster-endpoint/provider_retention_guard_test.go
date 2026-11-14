package main

// The Provider CLI package bounds how many superseded versions stay on disk, and
// the two settings that bound it are read by the maintainer script at install
// time. Nothing parses the operator reference at runtime, so a setting the script
// honours but the document omits produces no failure anywhere: the operator never
// sets it, the default silently applies, and a site that rolls back often has no
// way to learn that more history is available.
//
// The names and their defaults are read out of the script rather than restated
// here, because a hand-written copy is a second statement of the same fact and the
// copy nobody reads is the one that drifts. A default changed in the script and
// left stale in the document is the defect this guard exists for.
//
// These settings are deliberately absent from the Endpoint table: no production Go
// file reads them, so listing them there would fail the reverse check in
// TestEndpointEnvironmentNamesAreDocumented. That guard is not weakened to make
// room for them; they get their own section instead.

import (
	"regexp"
	"sort"
	"strconv"
	"strings"
	"testing"
)

const providerRetentionDocument = "docs/Environment_Variables.md"

const providerRetentionScript = "scripts/deb/postinst.provider"

// providerRetentionSectionHeading is the section that documents the install-time
// settings. It is separate from "## Endpoint" on purpose.
const providerRetentionSectionHeading = "\n## Provider package\n"

// providerRetentionDefaultPattern matches the shell default expansion that both
// declares the variable name and states the value used when it is unset.
var providerRetentionDefaultPattern = regexp.MustCompile(`\$\{(AGENT_CLUSTER_PROVIDER_RETENTION_[A-Z0-9_]+):-([0-9]+)\}`)

// providerRetentionRowPattern matches one row of the retention table, whose first
// cell is the backticked variable name and second cell the backticked default.
var providerRetentionRowPattern = regexp.MustCompile("(?m)^\\|\\s*`(AGENT_CLUSTER_PROVIDER_RETENTION_[A-Z0-9_]+)`\\s*\\|\\s*`([0-9]+)`\\s*\\|")

// retentionDefault is one declared default and the script line that declares it.
type retentionDefault struct {
	value string
	line  int
}

// providerRetentionDefaults returns each retention variable the script declares,
// paired with the default the script applies and the line that declares it.
func providerRetentionDefaults(t *testing.T, script string) map[string]retentionDefault {
	t.Helper()
	defaults := map[string]retentionDefault{}
	for _, match := range providerRetentionDefaultPattern.FindAllStringSubmatchIndex(script, -1) {
		name := script[match[2]:match[3]]
		value := script[match[4]:match[5]]
		defaults[name] = retentionDefault{value: value, line: lineAt(script, match[0])}
	}
	return defaults
}

// providerRetentionSection returns the text of the "## Provider package" section,
// stopping at the next top-level heading so the table is read without the prose
// that follows it.
func providerRetentionSection(t *testing.T, document string) string {
	t.Helper()
	start := strings.Index(document, providerRetentionSectionHeading)
	if start < 0 {
		t.Fatalf("%s has no \"## Provider package\" section, so the install-time retention settings are undocumented and this guard checked nothing", providerRetentionDocument)
	}
	rest := document[start:]
	end := strings.Index(rest[1:], "\n## ")
	if end < 0 {
		return rest
	}
	return rest[:end+1]
}

// TestProviderRetentionSettingsAreDocumented pins the contract between the
// maintainer script and the operator reference: every retention setting the script
// honours is documented, and the documented default is the default the script
// applies. A default that differs is worse than a missing row, because the operator
// reads a number that no longer bounds anything.
func TestProviderRetentionSettingsAreDocumented(t *testing.T) {
	root := repoRoot(t)
	script := readRepoFile(t, root, providerRetentionScript)
	document := readRepoFile(t, root, providerRetentionDocument)
	if strings.TrimSpace(document) == "" {
		t.Fatalf("%s is empty, so this guard checked nothing", providerRetentionDocument)
	}

	defaults := providerRetentionDefaults(t, script)
	if len(defaults) == 0 {
		t.Fatalf("%s declares no AGENT_CLUSTER_PROVIDER_RETENTION_ default, so the extraction pattern no longer matches the script and this guard checked nothing", providerRetentionScript)
	}

	section := providerRetentionSection(t, document)
	rows := map[string]string{}
	for _, match := range providerRetentionRowPattern.FindAllStringSubmatch(section, -1) {
		rows[match[1]] = match[2]
	}
	if len(rows) == 0 {
		t.Fatalf("%s has no retention table in its Provider package section, so this guard checked nothing", providerRetentionDocument)
	}

	names := make([]string, 0, len(defaults))
	for name := range defaults {
		names = append(names, name)
	}
	sort.Strings(names)

	missing := make([]string, 0, len(names))
	stale := make([]string, 0, len(names))
	for _, name := range names {
		documented, ok := rows[name]
		if !ok {
			missing = append(missing, name+" (defaulted at "+providerRetentionScript+":"+strconv.Itoa(defaults[name].line)+")")
			continue
		}
		if documented != defaults[name].value {
			stale = append(stale, name+" is documented as "+documented+" but "+providerRetentionScript+":"+strconv.Itoa(defaults[name].line)+" applies "+defaults[name].value)
		}
	}
	if len(missing) > 0 {
		t.Fatalf("%s does not document %d install-time retention setting(s) the Provider package honours: %s", providerRetentionDocument, len(missing), strings.Join(missing, ", "))
	}
	if len(stale) > 0 {
		t.Fatalf("%s states a retention default the Provider package does not apply: %s", providerRetentionDocument, strings.Join(stale, ", "))
	}

	// The installed version is never removed, because removing it would leave the
	// package installed with no payload. The script enforces it and the document
	// states it; a document that drops the sentence leaves an operator free to
	// assume the count applies to every directory on disk.
	if !strings.Contains(script, `[ "${name}" = "${PACKAGE_VERSION}" ] && continue`) {
		t.Fatalf("%s no longer skips the version it just installed, so the document's claim that the installed version is never removed is wrong", providerRetentionScript)
	}
	if !strings.Contains(section, "never removed") {
		t.Fatalf("%s does not state that the installed version is never removed, so an operator cannot tell whether the count applies to every version on disk", providerRetentionDocument)
	}
}
