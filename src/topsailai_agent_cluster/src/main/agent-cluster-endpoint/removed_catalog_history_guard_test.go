package main

// Two documents describe the Endpoint-local control-action catalog that
// `2b58a0a2` deleted. Nothing in the Endpoint reads either document, so a
// paragraph that still describes the catalog in the present tense produces no
// failure anywhere: a reader plans against a catalog that no longer exists, and
// the code cannot contradict a document nobody parses.
//
// The guard therefore compares two independent sources. One is the document
// text, which must mark the catalog as history. The other is the code on disk,
// which must still be free of the catalog parser and the placeholder fields. If
// either side changes, the two disagree and the guard fails.

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// removedCatalogDocuments are the documents that describe the deleted catalog.
var removedCatalogDocuments = []string{
	"docs/agent-cluster-adapters.md",
	"docs/agent-cluster-protocol.md",
}

// removedCatalogAnchor is the phrase every paragraph about the catalog carries.
const removedCatalogAnchor = "control-action catalog"

// removedCatalogHistoryMarkers are the words that mark the catalog as gone. The
// deletion commit is accepted because it names the change precisely; the verbs
// are accepted because a reader needs a plain statement, not a hash.
var removedCatalogHistoryMarkers = []string{
	"2b58a0a2",
	"deleted",
	"removed",
	"history",
}

// removedCatalogCodeRoots are the directories that must stay free of the
// catalog parser and its placeholder fields.
var removedCatalogCodeRoots = []string{"internal", "src"}

// removedCatalogCodeTokens are the placeholder identifiers the deleted catalog
// owned. A non-test Go file that mentions one of them means the catalog came
// back, and the documents that call it history are then wrong.
//
// The removed catalog file name is deliberately absent: control_action_comment_guard_test.go
// already pins that fact and scans every source file, so repeating the token here
// would make this guard's own file a hit and force that guard to be weakened.
var removedCatalogCodeTokens = []string{
	"payload_session_field",
	"PayloadSessionField",
}

// removedCatalogParagraph returns the paragraph of the document that names the
// catalog, so the guard reads the sentence a reader reads first.
func removedCatalogParagraph(t *testing.T, document, path string) string {
	t.Helper()
	for _, paragraph := range strings.Split(document, "\n\n") {
		if strings.Contains(paragraph, removedCatalogAnchor) {
			return paragraph
		}
	}
	t.Fatalf("%s has no paragraph naming the %q, so this guard checked nothing", path, removedCatalogAnchor)
	return ""
}

// removedCatalogHasHistoryMarker reports whether the paragraph marks the
// catalog as gone.
func removedCatalogHasHistoryMarker(paragraph string) bool {
	for _, marker := range removedCatalogHistoryMarkers {
		if strings.Contains(paragraph, marker) {
			return true
		}
	}
	return false
}

// removedCatalogCodeMentions walks the code roots and returns every non-test Go
// file that still mentions a token the deleted catalog owned.
func removedCatalogCodeMentions(t *testing.T, root string) []string {
	t.Helper()
	var mentions []string
	for _, codeRoot := range removedCatalogCodeRoots {
		walkRoot := filepath.Join(root, codeRoot)
		err := filepath.Walk(walkRoot, func(path string, info os.FileInfo, err error) error {
			if err != nil {
				return err
			}
			if info.IsDir() || !strings.HasSuffix(path, ".go") || strings.HasSuffix(path, "_test.go") {
				return nil
			}
			content, readErr := os.ReadFile(path)
			if readErr != nil {
				return readErr
			}
			text := string(content)
			for _, token := range removedCatalogCodeTokens {
				if strings.Contains(text, token) {
					relative, relErr := filepath.Rel(root, path)
					if relErr != nil {
						return relErr
					}
					mentions = append(mentions, relative+" mentions "+token)
					return nil
				}
			}
			return nil
		})
		if err != nil {
			t.Fatalf("walk %s: %v", walkRoot, err)
		}
	}
	return mentions
}

// TestRemovedControlCatalogIsDocumentedAsHistory pins the structural fact that
// every document describing the deleted catalog marks it as history, so a
// reader cannot mistake it for a mechanism still in force.
func TestRemovedControlCatalogIsDocumentedAsHistory(t *testing.T) {
	root := repoRoot(t)

	mentions := removedCatalogCodeMentions(t, root)
	if len(mentions) > 0 {
		t.Fatalf("the code still carries the deleted control-action catalog (%s), so the documents that call it history are wrong", strings.Join(mentions, "; "))
	}

	checked := 0
	for _, relative := range removedCatalogDocuments {
		document := readRepoFile(t, root, relative)
		if strings.TrimSpace(document) == "" {
			t.Fatalf("%s is empty, so this guard checked nothing", relative)
		}
		paragraph := removedCatalogParagraph(t, document, relative)
		checked++
		if !removedCatalogHasHistoryMarker(paragraph) {
			offset := strings.Index(document, paragraph)
			t.Fatalf("%s:%d describes the %q without marking it as history, so a reader plans against a catalog that 2b58a0a2 deleted", relative, lineAt(document, offset), removedCatalogAnchor)
		}
	}
	if checked != len(removedCatalogDocuments) {
		t.Fatalf("checked %d of %d documents, so this guard did not cover the set", checked, len(removedCatalogDocuments))
	}
}

// TestRemovedControlCatalogHeadingIsNotCurrent pins the heading of the section
// that describes the deleted catalog. A heading that still says "Current" tells
// a reader the mechanism is in force before the body can correct it.
func TestRemovedControlCatalogHeadingIsNotCurrent(t *testing.T) {
	root := repoRoot(t)
	relative := "docs/agent-cluster-protocol.md"
	document := readRepoFile(t, root, relative)
	if strings.TrimSpace(document) == "" {
		t.Fatalf("%s is empty, so this guard checked nothing", relative)
	}

	lines := strings.Split(document, "\n")
	headingLine := -1
	for index, line := range lines {
		if !strings.HasPrefix(line, "#") {
			continue
		}
		if strings.Contains(strings.ToLower(line), "control catalog") {
			headingLine = index
			break
		}
	}
	if headingLine < 0 {
		t.Fatalf("%s has no heading naming the control catalog, so this guard checked nothing", relative)
	}
	heading := lines[headingLine]
	if strings.Contains(strings.ToLower(heading), "current") {
		t.Fatalf("%s:%d keeps the heading %q for a catalog that 2b58a0a2 deleted, so a reader believes the mechanism is in force", relative, headingLine+1, strings.TrimSpace(heading))
	}
}
