package main

// The catalog reference document tells an operator where the catalog comes from.
// Nothing in the Endpoint reads that document, and nothing in the Endpoint reads
// the catalog either, so a document that implies a fresh node already has one
// produces no failure anywhere: the operator looks for a file that was never
// installed, finds nothing, and every ctl. operation is refused as unsupported.
//
// The guard therefore compares two independent sources. One is the document text,
// which must say the example is a repository reference rather than an installed
// file. The other is the deployment scripts on disk, which must not claim to ship
// a catalog. If either side changes, the two disagree and the guard fails.
//
// This guard deliberately does not repeat the filename check in
// catalog_deployment_guard_test.go. That one pins "no deployment script mentions
// control-actions.conf"; this one pins "no deployment script claims to ship a
// control action catalog", which is the sentence an operator actually reads.

import (
	"io/fs"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// catalogReferenceDocument is the document that explains where the catalog lives.
const catalogReferenceDocument = "conf/control-actions.md"

// catalogReferenceExample is the repository file the document points at.
const catalogReferenceExample = "conf/control-actions.conf.example"

// catalogShippingClaim is the phrase a deployment script uses when it claims to
// ship the catalog. It is spelled out here because the guard has to look for it.
const catalogShippingClaim = "control action catalog"

// catalogNegations are the words that turn a shipping claim into a denial. A
// script may explain that it ships no catalog; that is the correct statement and
// must not be reported.
var catalogNegations = []string{"no ", "not ", "never", "ships no", "without"}

// catalogScriptRoot is the directory that holds every deployment path.
const catalogScriptRoot = "scripts"

// catalogReferenceParagraph returns the paragraph of the document that names the
// example file, so the guard reads the sentence an operator reads first.
func catalogReferenceParagraph(t *testing.T, document string) string {
	t.Helper()
	for _, paragraph := range strings.Split(document, "\n\n") {
		if strings.Contains(paragraph, catalogReferenceExample) {
			return paragraph
		}
	}
	t.Fatalf("%s never names %s, so this guard checked nothing", catalogReferenceDocument, catalogReferenceExample)
	return ""
}

// TestCatalogDocumentSaysTheExampleIsNotInstalled pins the structural fact that
// the document describes the example as a repository reference and that the
// deployment scripts agree by shipping no catalog.
func TestCatalogDocumentSaysTheExampleIsNotInstalled(t *testing.T) {
	root := repoRoot(t)

	document := readRepoFile(t, root, catalogReferenceDocument)
	paragraph := catalogReferenceParagraph(t, document)
	lowered := strings.ToLower(paragraph)

	// The document must deny installation. Without this sentence an operator
	// reads "the catalog in conf/control-actions.conf.example" as "the file is
	// already there".
	denied := false
	for _, phrase := range []string{"no deployment path", "not an installed file"} {
		if strings.Contains(lowered, phrase) {
			denied = true
			break
		}
	}
	if !denied {
		t.Errorf("%s does not say the example is a repository reference rather than an installed file, so an operator expects a catalog on a fresh node", catalogReferenceDocument)
	}

	// The document must also say how the file reaches the Provider, because a
	// denial without a next step leaves the operator stuck.
	if !strings.Contains(lowered, "by hand") {
		t.Errorf("%s does not say the operator copies the example by hand, so the denial names no way forward", catalogReferenceDocument)
	}

	// The example must exist, otherwise "repository reference" is false.
	if _, err := os.Stat(filepath.Join(root, catalogReferenceExample)); err != nil {
		t.Fatalf("stat %s: %v", filepath.Join(root, catalogReferenceExample), err)
	}

	// The deployment scripts must agree. A script that claims to ship the
	// catalog contradicts the document, and the operator believes the script.
	scanned := 0
	covered := map[string]bool{}
	walkErr := filepath.WalkDir(filepath.Join(root, catalogScriptRoot), func(path string, entry fs.DirEntry, err error) error {
		if err != nil {
			return err
		}
		if entry.IsDir() {
			return nil
		}
		content, readErr := os.ReadFile(path)
		if readErr != nil {
			return readErr
		}
		scanned++
		if relative, relErr := filepath.Rel(root, path); relErr == nil {
			covered[relative] = true
		}
		lines := strings.Split(string(content), "\n")
		for index, line := range lines {
			if !strings.Contains(strings.ToLower(line), catalogShippingClaim) {
				continue
			}
			// The negation must sit on the same line, before the claim. A wider
			// window is wrong: the sentence after a shipping claim often says
			// "not interchangeable between machines", and reading that as a
			// denial would let the stale claim through. Only the text before the
			// phrase can negate it.
			loweredLine := strings.ToLower(line)
			before := loweredLine[:strings.Index(loweredLine, catalogShippingClaim)]
			negated := false
			for _, negation := range catalogNegations {
				if strings.Contains(before, negation) {
					negated = true
					break
				}
			}
			if negated {
				continue
			}
			relative, relErr := filepath.Rel(root, path)
			if relErr != nil {
				relative = path
			}
			t.Errorf("%s:%d claims to ship a %s, but %s says no deployment path ships it", relative, index+1, catalogShippingClaim, catalogReferenceDocument)
		}
		return nil
	})
	if walkErr != nil {
		t.Fatalf("walk %s: %v", catalogScriptRoot, walkErr)
	}
	if scanned == 0 {
		t.Fatalf("no file was read under %s, so this guard checked nothing", catalogScriptRoot)
	}
	// The correct state is that no script mentions the catalog at all, so a zero
	// claim count is the expected result and cannot be the "checked nothing"
	// signal. The signal is coverage instead: every deployment path that could
	// ship a catalog must have been read. A renamed or deleted script fails here
	// rather than silently shrinking the scan.
	for _, relative := range catalogDeploymentScripts {
		if !covered[relative] {
			t.Fatalf("%s was not read under %s, so this guard did not check the deployment path that could ship a catalog", relative, catalogScriptRoot)
		}
	}
}
