package main

// Two documents describe how the control action catalog reaches a node, and both
// claims are about files outside this package: the Provider CLI source that names
// the environment variable, and the deployment scripts that decide what a package
// installs. Nothing in the Endpoint reads either of them, so a document that
// describes a previous deployment produces no failure anywhere. The operator then
// expects a catalog on a fresh node, finds none, and every ctl. operation is
// refused as unsupported with no hint about why.
//
// The guards read the Provider source and the deployment scripts instead of
// restating them. If the Provider renames the variable, or a deployment path starts
// shipping the catalog, the guard fails rather than letting the documents drift.

import (
	"regexp"
	"strings"
	"testing"
)

// catalogSourceFile declares the environment variable the Provider reads.
const catalogSourceFile = "providers/topsailai/src/mutation_control.go"

// catalogEnvironmentPattern reads the constant out of the Provider source.
var catalogEnvironmentPattern = regexp.MustCompile(`const\s+controlActionsEnvironment\s*=\s*"([^"]*)"`)

// catalogEnvironmentTokenPattern finds any cluster environment variable name. It
// deliberately does not require the name to contain CONTROL_ACTION: a renamed
// variable is exactly the drift this guard exists for, and a narrower pattern
// would skip the renamed token instead of reporting it. The removed Endpoint key
// also matches, which is why a token is only treated as a claim when the
// surrounding text attributes catalog reading to the Provider.
var catalogEnvironmentTokenPattern = regexp.MustCompile(`AGENT_CLUSTER_[A-Z0-9_]+`)

// catalogDocumentedFiles describe where the catalog comes from.
var catalogDocumentedFiles = []string{
	"conf/control-actions.md",
	"docs/Environment_Variables.md",
}

// catalogDeploymentScripts are the two paths that build a node.
var catalogDeploymentScripts = []string{
	"scripts/make-deb.sh",
	"scripts/make-node-bundle.sh",
}

// catalogFileName is the installed name the documents used to promise.
const catalogFileName = "control-actions.conf"

// readCatalogEnvironment returns the environment variable the Provider actually
// reads, taken from its own source.
func readCatalogEnvironment(t *testing.T, root string) string {
	t.Helper()
	source := readRepoFile(t, root, catalogSourceFile)
	match := catalogEnvironmentPattern.FindStringSubmatch(source)
	if match == nil {
		t.Fatalf("%s does not declare controlActionsEnvironment as a string constant, so the guard cannot read the real name", catalogSourceFile)
	}
	if match[1] == "" {
		t.Fatalf("%s declares an empty controlActionsEnvironment", catalogSourceFile)
	}
	return match[1]
}

// TestDocumentedCatalogEnvironmentMatchesTheProvider pins the structural fact that
// every environment variable a document attributes to the Provider reading the
// catalog is the variable the Provider actually reads.
func TestDocumentedCatalogEnvironmentMatchesTheProvider(t *testing.T) {
	root := repoRoot(t)
	want := readCatalogEnvironment(t, root)

	type occurrence struct {
		file  string
		line  int
		token string
	}
	var found []occurrence

	for _, relative := range catalogDocumentedFiles {
		content := readRepoFile(t, root, relative)
		lines := strings.Split(content, "\n")
		for index, line := range lines {
			matches := catalogEnvironmentTokenPattern.FindAllString(line, -1)
			if len(matches) == 0 {
				continue
			}
			// A token is a claim about the Provider only when the surrounding
			// text says the Provider reads the catalog. The removed Endpoint key
			// is described in the same document as a key that is no longer read,
			// and it must not be compared against the Provider variable.
			start := index - 2
			if start < 0 {
				start = 0
			}
			window := strings.ToLower(strings.Join(lines[start:index+1], " "))
			if !strings.Contains(window, "provider") || !strings.Contains(window, "catalog") {
				continue
			}
			for _, token := range matches {
				found = append(found, occurrence{file: relative, line: index + 1, token: token})
			}
		}
	}

	if len(found) == 0 {
		t.Fatalf("no document in %v attributes catalog reading to the Provider, so this guard checked nothing", catalogDocumentedFiles)
	}

	for _, item := range found {
		if item.token == want {
			continue
		}
		t.Errorf("%s:%d names %s as the catalog environment variable, but %s declares %s", item.file, item.line, item.token, catalogSourceFile, want)
	}
}

// TestNoDeploymentPathInstallsTheCatalog pins the structural fact that the catalog
// is Provider-side configuration no package ships, and that no document claims
// otherwise.
func TestNoDeploymentPathInstallsTheCatalog(t *testing.T) {
	root := repoRoot(t)

	for _, relative := range catalogDeploymentScripts {
		content := readRepoFile(t, root, relative)
		if strings.TrimSpace(content) == "" {
			t.Fatalf("%s is empty, so this guard read nothing", relative)
		}
		if strings.Contains(content, catalogFileName) {
			t.Errorf("%s mentions %s, but the catalog is Provider-side configuration and no deployment path installs it", relative, catalogFileName)
		}
	}

	// The feature record must not claim a deployment path registers the catalog
	// as a conffile. That claim is what made an operator expect a fresh node to
	// have a catalog.
	// The claim spans a sentence, and a sentence wraps across lines. Checking one
	// line at a time missed the original wording, where "deployment paths" sat on
	// one line and "conffile" on the next, so the window below covers the whole
	// sentence a claim can occupy.
	feature := readRepoFile(t, root, "features/90ai-added.md")
	lines := strings.Split(feature, "\n")
	claims := 0
	for index, line := range lines {
		if !strings.Contains(strings.ToLower(line), "deployment path") {
			continue
		}
		claims++
		end := index + 3
		if end > len(lines) {
			end = len(lines)
		}
		window := strings.ToLower(strings.Join(lines[index:end], " "))
		if strings.Contains(window, "conffile") {
			t.Errorf("features/90ai-added.md:%d claims a deployment path registers the catalog as a conffile, but no deployment script installs it", index+1)
		}
	}
	if claims == 0 {
		t.Fatalf("features/90ai-added.md says nothing about a deployment path, so this guard checked nothing")
	}
}
