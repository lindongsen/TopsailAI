package main

// features/90ai-added.md records features the AI added. One section describes the
// Endpoint-local control action catalog, and that mechanism no longer exists:
// 0391ba56 deleted it in full, so the package path, the key and the helpers the
// section names are history.
//
// The section is dangerous in one specific way. Its opening paragraphs were written
// in the present tense while the mechanism was live, so a reader who trusts them
// looks for internal/adapter/topsailai/ctl_config.go, sets the Endpoint-side catalog
// key, and expects a catalog to take effect. The file is gone and the key is read by
// nothing, so the reader's node advertises no ctl. action and nothing reports why.
//
// Nothing reads the feature record at runtime, so a stale section produces no error
// and no failing test. The guard therefore reads the file as text and requires the
// section to be labelled as history at its top, to name the dead identifiers only
// inside paragraphs that say they are gone, and to state the current mechanism.
//
// This guard does not reuse catalog_reference_guard_test.go. That guard pins
// conf/control-actions.md, which tells an operator how to configure the catalog
// today. This guard pins the feature record, which tells a reader what was built and
// when it was removed. The two files fail for different reasons and are edited by
// different changes, so one guard cannot cover both.

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// featuresRecord is the feature record the AI maintains.
const featuresRecord = "features/90ai-added.md"

// featuresCatalogHeading is the level-two heading of the deleted catalog section.
const featuresCatalogHeading = "Config-file-driven ctl catalog"

// featuresDeadPackage is the adapter package the deleted mechanism lived in.
const featuresDeadPackage = "internal/adapter/topsailai"

// featuresDeadKey is the Endpoint-side catalog key, split so the continuous-string
// scan in TestNoSourceReadsTheRemovedControlActionFile does not read this file as a
// source file that still references it.
var featuresDeadKey = "AGENT_CLUSTER_ENDPOINT_CONTROL_ACTION" + "_FILE"

// featuresCurrentKey is the key the Provider reads today.
const featuresCurrentKey = "AGENT_CLUSTER_TOPSAILAI_CONTROL_ACTIONS"

// featuresHistoryMarkers are the phrases that mark a paragraph as history rather
// than as a description of the current mechanism. A bare "no longer" is deliberately
// absent: the section's opening paragraph says the old helper "no longer carries a
// compiled-in action list", which is a change inside the old mechanism rather than a
// statement that the mechanism is gone. Accepting that phrase would let the whole
// present-tense paragraph pass as history.
var featuresHistoryMarkers = []string{
	"0391ba56",
	"deleted",
	"removed",
	"no longer exists",
	"no longer read",
	"no longer ships",
	"is gone",
	"history",
	"former",
}

// featuresParagraph is one paragraph of a section body with its byte offset.
type featuresParagraph struct {
	Text   string
	Offset int
}

// featuresSection returns the body of the named level-two section and the byte
// offset where that body starts. The body excludes the heading line and ends at the
// next level-two heading or at the end of the file.
func featuresSection(text, heading string) (string, int, bool) {
	marker := "\n## " + heading + "\n"
	index := strings.Index(text, marker)
	if index < 0 {
		return "", 0, false
	}
	start := index + len(marker)
	rest := text[start:]
	if end := strings.Index(rest, "\n## "); end >= 0 {
		return rest[:end], start, true
	}
	return rest, start, true
}

// featuresParagraphs splits a section body into paragraphs, keeping each paragraph's
// byte offset so a failure can name the line a reader would look at.
func featuresParagraphs(body string) []featuresParagraph {
	var paragraphs []featuresParagraph
	offset := 0
	for offset <= len(body) {
		end := strings.Index(body[offset:], "\n\n")
		next := len(body) + 1
		var text string
		if end < 0 {
			text = body[offset:]
		} else {
			text = body[offset : offset+end]
			next = offset + end + 2
		}
		trimmed := strings.TrimLeft(text, "\n")
		if strings.TrimSpace(trimmed) != "" {
			// The offset must point at the first line a reader sees, not at the blank
			// line that separates paragraphs, or a failure names the wrong line.
			paragraphs = append(paragraphs, featuresParagraph{Text: trimmed, Offset: offset + len(text) - len(trimmed)})
		}
		offset = next
	}
	return paragraphs
}

// featuresHasHistoryMarker reports whether the text carries a phrase that marks it
// as history.
func featuresHasHistoryMarker(text string) bool {
	lowered := strings.ToLower(text)
	for _, marker := range featuresHistoryMarkers {
		if strings.Contains(lowered, marker) {
			return true
		}
	}
	return false
}

// featuresCatalogSection reads the feature record and returns the deleted catalog
// section together with the file text and the body offset.
func featuresCatalogSection(t *testing.T) (string, string, int) {
	t.Helper()
	root := repoRoot(t)
	path := filepath.Join(root, featuresRecord)
	content, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("read %s: %v", path, err)
	}
	text := string(content)
	if strings.TrimSpace(text) == "" {
		t.Fatalf("%s is empty, so this guard checked nothing", featuresRecord)
	}
	body, offset, ok := featuresSection(text, featuresCatalogHeading)
	if !ok {
		t.Fatalf("%s has no %q section, so this guard checked nothing", featuresRecord, featuresCatalogHeading)
	}
	if strings.TrimSpace(body) == "" {
		t.Fatalf("%s has an empty %q section, so this guard checked nothing", featuresRecord, featuresCatalogHeading)
	}
	return text, body, offset
}

// TestFeaturesRecordBannerLabelsTheDeletedCatalogAsHistory pins the structural fact
// that the section opens by saying the mechanism is gone and naming the commit that
// deleted it, so a reader cannot mistake the whole section for current behaviour.
func TestFeaturesRecordBannerLabelsTheDeletedCatalogAsHistory(t *testing.T) {
	text, body, offset := featuresCatalogSection(t)

	paragraphs := featuresParagraphs(body)
	if len(paragraphs) == 0 {
		t.Fatalf("%s has no paragraph under %q, so this guard checked nothing", featuresRecord, featuresCatalogHeading)
	}

	first := paragraphs[0]
	line := lineAt(text, offset+first.Offset)
	if !featuresHasHistoryMarker(first.Text) {
		t.Errorf("%s:%d opens the deleted catalog section without a history marker, so a reader treats the whole section as the current mechanism", featuresRecord, line)
	}
	if !strings.Contains(first.Text, "0391ba56") {
		t.Errorf("%s:%d opens the deleted catalog section without naming the commit that deleted it, so a reader cannot check the claim", featuresRecord, line)
	}
}

// TestFeaturesRecordNamesTheDeletedCatalogOnlyAsHistory pins the structural fact
// that every paragraph naming the deleted package or the dead key also says it is
// gone, so a reader never looks for a file that no longer exists or sets a key
// nothing reads.
func TestFeaturesRecordNamesTheDeletedCatalogOnlyAsHistory(t *testing.T) {
	text, body, offset := featuresCatalogSection(t)

	checked := 0
	for _, paragraph := range featuresParagraphs(body) {
		named := strings.Contains(paragraph.Text, featuresDeadPackage) || strings.Contains(paragraph.Text, featuresDeadKey)
		if !named {
			continue
		}
		checked++
		if featuresHasHistoryMarker(paragraph.Text) {
			continue
		}
		t.Errorf("%s:%d names the deleted catalog package or key without saying it is gone, so a reader looks for a file that no longer exists and sets a key nothing reads", featuresRecord, lineAt(text, offset+paragraph.Offset))
	}

	// A renamed package, a rewritten key or a reworded section must fail here rather
	// than shrink the scan to nothing.
	if checked == 0 {
		t.Fatalf("%s names neither %s nor the removed control action key, so this guard checked nothing", featuresRecord, featuresDeadPackage)
	}
}

// TestFeaturesRecordStatesTheCurrentCatalogMechanism pins the structural fact that
// the section ends by naming the mechanism that replaced the deleted one, so a
// reader who learns the old design also learns where the capability list lives now.
func TestFeaturesRecordStatesTheCurrentCatalogMechanism(t *testing.T) {
	text, body, offset := featuresCatalogSection(t)

	if !strings.Contains(body, featuresCurrentKey) {
		t.Errorf("%s:%d does not name %s as the key the Provider reads today, so a reader has no current mechanism to follow", featuresRecord, lineAt(text, offset), featuresCurrentKey)
	}
	if !strings.Contains(body, "ADAPTERS") {
		t.Errorf("%s:%d does not say the ctl. capabilities come from the ADAPTERS document, so a reader cannot tell where the capability list lives", featuresRecord, lineAt(text, offset))
	}
}
