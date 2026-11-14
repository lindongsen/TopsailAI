package main

// The project lesson file records how a defect was found and fixed. One entry
// describes a launcher that never forwarded the control action catalog path, and
// that entry is the only place in the file that names the dead key.
//
// The entry is dangerous in one specific way. Its Trigger paragraph describes the
// missing forwarding step as a live defect, so a reader who stops there concludes
// that the launcher still needs one more `args+=` line. The defect was in fact
// closed by deleting the whole Endpoint-side catalog, so adding that line would
// forward a key nothing reads and the `ctl.` capability would still be absent.
//
// Nothing reads the lesson file at runtime, so a stale entry produces no error and
// no failing test. The guard therefore reads the file as text and requires that the
// entry naming the dead key also states how the defect was closed.

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// learnFile is the project lesson file.
const learnFile = "LEARN.md"

// learnRemovedKey is the dead key, split so the continuous-string scan in
// TestNoSourceReadsTheRemovedControlActionFile does not read this file as a source
// file that still references it.
var learnRemovedKey = "CONTROL_ACTION" + "_FILE"

// learnResolutionMarkers are the phrases that distinguish a closed defect from an
// open one. A lesson entry that names the dead key must carry at least one of them,
// because the key was removed rather than wired up.
var learnResolutionMarkers = []string{
	"resolved by removal",
	"no longer read",
	"0391ba56",
	"2b58a0a2",
	"ADAPTERS",
	"AGENT_CLUSTER_TOPSAILAI_CONTROL_ACTIONS",
}

// learnSection returns the section that contains the given offset: the text from
// the nearest preceding level-two heading through the next level-two heading. A
// lesson entry is read as one section, so the resolution may sit in its own
// paragraph without being separated from the defect it closes.
func learnSection(text string, offset int) string {
	start := strings.LastIndex(text[:offset], "\n## ")
	if start < 0 {
		start = 0
	} else {
		start++
	}
	end := strings.Index(text[offset:], "\n## ")
	if end < 0 {
		return text[start:]
	}
	return text[start : end+offset]
}

// lineAt returns the one-based line number of the given offset.
func lineAt(text string, offset int) int {
	return strings.Count(text[:offset], "\n") + 1
}

// TestLearnEntryNamingTheRemovedKeyStatesHowItWasClosed pins the structural fact
// that the lesson entry which names the dead key also says the defect was closed by
// removal, so a reader cannot mistake it for a forwarding step still to be added.
func TestLearnEntryNamingTheRemovedKeyStatesHowItWasClosed(t *testing.T) {
	root := repoRoot(t)
	path := filepath.Join(root, learnFile)
	content, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("read %s: %v", path, err)
	}

	text := string(content)
	if strings.TrimSpace(text) == "" {
		t.Fatalf("%s is empty, so this guard checked nothing", learnFile)
	}

	mentions := 0
	for offset := 0; offset < len(text); {
		found := strings.Index(text[offset:], learnRemovedKey)
		if found < 0 {
			break
		}
		position := offset + found
		offset = position + len(learnRemovedKey)
		mentions++

		section := learnSection(text, position)
		lowered := strings.ToLower(section)
		closed := false
		for _, marker := range learnResolutionMarkers {
			if strings.Contains(lowered, strings.ToLower(marker)) {
				closed = true
				break
			}
		}
		if closed {
			continue
		}
		t.Errorf("%s:%d names the removed control action key in a lesson entry that never says the defect was closed by removal, so a reader adds a forwarding step for a key nothing reads", learnFile, lineAt(text, position))
	}

	// A renamed key or a rewritten file must fail here rather than shrink the scan
	// to nothing.
	if mentions == 0 {
		t.Fatalf("%s mentions no removed control action key, so this guard checked nothing", learnFile)
	}
}
