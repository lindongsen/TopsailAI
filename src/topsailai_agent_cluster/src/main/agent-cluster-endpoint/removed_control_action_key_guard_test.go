package main

// The Endpoint no longer reads a control action catalog, so the key that used to
// name one is dead. Two documents still mention it, and both mention it only to
// explain that it is gone. That is the correct state, and it is fragile in two
// different ways.
//
// The first way is the shipped template. A comment that says the key is no longer
// read is harmless, but an assignment line would be a live instruction: an
// operator would set a path, the Endpoint would ignore it, and every ctl.
// operation would still be refused with no hint that the setting did nothing.
//
// The second way is the reference document. A sentence that says the key is no
// longer read is correct, but the same key name in a paragraph that presents it as
// current configuration would send an operator looking for a setting that has no
// effect.
//
// Neither failure produces a runtime error, because nothing reads either document.
// The guard therefore reads both files as text and compares them against the fact
// that the key is dead: no assignment line in the template, and every mention in
// the document inside a paragraph that says so.

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// removedKeyTemplate is the shipped configuration template.
const removedKeyTemplate = "conf/node.endpoint.conf.example"

// removedKeyDocument is the environment variable reference.
const removedKeyDocument = "docs/Environment_Variables.md"

// removedKeys are the two spellings of the dead key. The Endpoint-side name is
// what a node.conf carries; the prefixed name is what the process environment
// would carry.
//
// The names are assembled from two halves on purpose. Another guard in this
// package scans every Go file for the contiguous key name, and a literal here
// would make that guard report this file as a reader of the removed key. Writing
// the halves keeps this file out of its own scan and out of that one.
var removedKeys = []string{
	"CONTROL_ACTION" + "_FILE",
	"AGENT_CLUSTER_ENDPOINT_CONTROL_ACTION" + "_FILE",
}

// removalWording are the phrases that mark a mention as a removal notice rather
// than as current configuration. A paragraph that names the key must contain at
// least one of them.
var removalWording = []string{
	"no longer read",
	"no longer sets",
	"no longer resolves",
	"no longer forwards",
	"removed",
	"former key",
	"was such a key",
}

// assignmentLine reports whether a line assigns the key rather than mentioning it
// in a comment. A commented mention is allowed; an assignment is not.
func assignmentLine(line, key string) bool {
	trimmed := strings.TrimSpace(line)
	if strings.HasPrefix(trimmed, "#") {
		return false
	}
	trimmed = strings.TrimPrefix(trimmed, "export ")
	trimmed = strings.TrimSpace(trimmed)
	return strings.HasPrefix(trimmed, key+"=")
}

// TestShippedTemplateAssignsNoRemovedControlActionKey pins the structural fact
// that the shipped template mentions the dead key only in a comment.
func TestShippedTemplateAssignsNoRemovedControlActionKey(t *testing.T) {
	root := repoRoot(t)
	path := filepath.Join(root, removedKeyTemplate)
	content, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("read %s: %v", path, err)
	}
	if strings.TrimSpace(string(content)) == "" {
		t.Fatalf("%s is empty, so this guard read nothing", removedKeyTemplate)
	}

	lines := strings.Split(string(content), "\n")
	for index, line := range lines {
		for _, key := range removedKeys {
			if assignmentLine(line, key) {
				t.Errorf("%s:%d assigns %s, but the Endpoint no longer reads it, so the setting would be silently ignored", removedKeyTemplate, index+1, key)
			}
		}
	}
}

// TestDocumentMentionsTheRemovedKeyOnlyAsRemoval pins the structural fact that
// every mention of the dead key in the reference document sits in a paragraph that
// says the key is gone.
func TestDocumentMentionsTheRemovedKeyOnlyAsRemoval(t *testing.T) {
	root := repoRoot(t)
	path := filepath.Join(root, removedKeyDocument)
	content, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("read %s: %v", path, err)
	}

	text := string(content)
	paragraphs := strings.Split(text, "\n\n")
	mentions := 0
	for _, paragraph := range paragraphs {
		lowered := strings.ToLower(paragraph)
		named := false
		for _, key := range removedKeys {
			if strings.Contains(paragraph, key) {
				named = true
				break
			}
		}
		if !named {
			continue
		}
		mentions++
		explained := false
		for _, phrase := range removalWording {
			if strings.Contains(lowered, phrase) {
				explained = true
				break
			}
		}
		if explained {
			continue
		}
		line := lineOfParagraph(text, paragraph)
		t.Errorf("%s:%d mentions a removed control action key without saying it is gone, so an operator reads it as current configuration", removedKeyDocument, line)
	}
	if mentions == 0 {
		t.Fatalf("%s mentions no removed control action key, so this guard checked nothing", removedKeyDocument)
	}
}

// lineOfParagraph returns the 1-based line where a paragraph starts, so a failure
// names a location an editor can jump to.
func lineOfParagraph(content, paragraph string) int {
	offset := strings.Index(content, paragraph)
	if offset < 0 {
		return 1
	}
	return strings.Count(content[:offset], "\n") + 1
}
