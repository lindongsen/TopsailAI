package main

// The guards in this file read documentation and installer text instead of
// calling functions, because the regression they exist for is a shape, not a
// value. Nothing in the Endpoint parses these documents at runtime, so a
// documented command path that no longer matches the installed layout produces
// no failure anywhere: the operator copies the example, the Endpoint starts,
// and the first provider invocation fails with "no such file". Only reading the
// two texts and comparing their structure can catch that before an operator
// does.
//
// The install layout is not restated here. It is read out of
// scripts/deb/postinst.provider, which is the single place that decides where a
// provider package puts its payload. If that script moves the payload, this
// guard fails, which is the point: the document and the installer cannot drift
// apart without a test noticing.

import (
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"testing"
)

// documentedAdapterFiles are the documents that show an ADAPTERS example. The
// list is explicit rather than a repository walk: a walk silently stops
// covering a file that was renamed, while an explicit list fails loudly with
// the path that disappeared.
var documentedAdapterFiles = []string{
	"conf/node.endpoint.conf.example",
	"tests/environment-variables/endpoint.feature.md",
}

// adapterCommandPattern extracts the command value from an ADAPTERS example. A
// JSON decoder cannot be used: in the conf example the document is embedded in
// a single-quoted shell assignment, and in the feature document it sits inside
// a Markdown table cell, so neither is a standalone JSON document.
var adapterCommandPattern = regexp.MustCompile(`"command"\s*:\s*"([^"]*)"`)

// providerRootPattern reads the install root out of the post-install script.
var providerRootPattern = regexp.MustCompile(`PROVIDER_ROOT="([^"]*)\$\{PROVIDER_TYPE\}"`)

// providerBinaryPattern reads the payload file name out of the post-install
// script.
var providerBinaryPattern = regexp.MustCompile(`BINARY="\$\{VERSION_DIR\}/([^"]*)\$\{PROVIDER_TYPE\}"`)

// installLayout is the payload layout the provider package actually installs.
type installLayout struct {
	rootPrefix   string
	binaryPrefix string
}

// repoRoot resolves the repository root from this test file's directory, so the
// guard works from any checkout location.
func repoRoot(t *testing.T) string {
	t.Helper()
	root, err := filepath.Abs(filepath.Join("..", "..", ".."))
	if err != nil {
		t.Fatalf("resolve repository root: %v", err)
	}
	return root
}

// readRepoFile reads one repository file and reports the concrete path when it
// is missing, so a renamed document names itself instead of failing vaguely.
func readRepoFile(t *testing.T, root, relative string) string {
	t.Helper()
	path := filepath.Join(root, relative)
	content, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("read %s: %v", path, err)
	}
	return string(content)
}

// readInstallLayout extracts the layout from the post-install script.
func readInstallLayout(t *testing.T, root string) installLayout {
	t.Helper()
	script := readRepoFile(t, root, "scripts/deb/postinst.provider")

	rootMatch := providerRootPattern.FindStringSubmatch(script)
	if rootMatch == nil {
		t.Fatalf("scripts/deb/postinst.provider does not define PROVIDER_ROOT as a literal prefix plus ${PROVIDER_TYPE}, so the guard cannot read the install root")
	}
	binaryMatch := providerBinaryPattern.FindStringSubmatch(script)
	if binaryMatch == nil {
		t.Fatalf("scripts/deb/postinst.provider does not define BINARY as ${VERSION_DIR}/<prefix>${PROVIDER_TYPE}, so the guard cannot read the payload name")
	}
	return installLayout{rootPrefix: rootMatch[1], binaryPrefix: binaryMatch[1]}
}

// TestDocumentedAdapterCommandMatchesTheInstalledLayout pins the structural
// fact that every documented adapter command names a payload at the path the
// provider package actually installs.
func TestDocumentedAdapterCommandMatchesTheInstalledLayout(t *testing.T) {
	root := repoRoot(t)
	layout := readInstallLayout(t, root)

	type occurrence struct {
		file  string
		line  int
		value string
	}
	var found []occurrence

	for _, relative := range documentedAdapterFiles {
		content := readRepoFile(t, root, relative)
		for lineIndex, line := range strings.Split(content, "\n") {
			for _, match := range adapterCommandPattern.FindAllStringSubmatch(line, -1) {
				found = append(found, occurrence{file: relative, line: lineIndex + 1, value: match[1]})
			}
		}
	}

	if len(found) == 0 {
		t.Fatalf("no adapter command example was found in %v, so this guard checked nothing", documentedAdapterFiles)
	}

	for _, item := range found {
		remainder, ok := strings.CutPrefix(item.value, layout.rootPrefix)
		if !ok {
			t.Errorf("%s:%d documents command %q, which is not under the installed root %q", item.file, item.line, item.value, layout.rootPrefix)
			continue
		}
		segments := strings.Split(remainder, "/")
		if len(segments) != 3 {
			t.Errorf("%s:%d documents command %q, want %q<provider-type>/<version>/<payload>", item.file, item.line, item.value, layout.rootPrefix)
			continue
		}
		providerType, version, payload := segments[0], segments[1], segments[2]
		if providerType == "" {
			t.Errorf("%s:%d documents command %q with an empty provider type directory", item.file, item.line, item.value)
			continue
		}
		if version == "" {
			t.Errorf("%s:%d documents command %q with an empty version directory", item.file, item.line, item.value)
			continue
		}
		wantPayload := layout.binaryPrefix + providerType
		if payload != wantPayload {
			t.Errorf("%s:%d documents command %q whose payload is %q, but the installer names it %q for provider type %q", item.file, item.line, item.value, payload, wantPayload, providerType)
		}
	}
}
