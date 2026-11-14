package main

import (
	"encoding/json"
	"os"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
	"testing"
)

// This guard exists because conf/control-actions.md is the reference an operator
// reads to decide what a rejection means, and prose keeps reading as fact after
// the code that produced it is gone. The document said a disagreeing constant is
// reported as control_payload_conflict, distinct from control_action_unconfigured,
// while neither code existed in any Go file: controlConstantPayload returns
// errInvalidRequest and the catalog lookup returns errUnsupported before any argv
// exists. A reader who saw a rejection looked for a code that could never appear.
//
// It is separate from manual_evidence_citation_guard_test.go, which pins the
// manual harness documents, and from catalog_reference_guard_test.go, which pins
// what the documents say about configuration. This one pins two things about the
// catalog reference: every error code it attributes to a rejection must be one the
// provider can emit, and every count it states about the shipped catalog must
// equal the count parsed from the catalog file.

// controlActionReferenceFile is the catalog reference an operator reads.
const controlActionReferenceFile = "conf/control-actions.md"

// controlActionCatalogFile is the shipped catalog the reference describes.
const controlActionCatalogFile = "conf/control-actions.conf.example"

// rejectionAttribution matches a phrase that attributes an error code to a
// rejection, followed by the backticked code it names.
//
// The phrases are the ones this document uses to say "this rejection reports this
// code". A phrase outside this set is not checked, which is a real limit: a future
// sentence that attributes a dead code with different wording would pass. The set
// is kept to the wording the document actually uses so the guard reports the
// claims it can read rather than guessing at prose.
var rejectionAttribution = regexp.MustCompile("(?:reported|refused|rejected) as `([a-z][a-z0-9_]*)`")

// externalCliErrorClaims are codes this document attributes to the TopsailAI
// business CLI rather than to the provider, so they cannot be checked against the
// provider source.
//
// The exclusion is explicit and carries its reason, because a silent skip would
// hide the limitation. invalid_payload is the heartbeat handler's own error string
// in the business CLI; the only invalid_payload in this repository is the
// command.exec decode path in internal/adapter/genericcli/command_exec.go, which is
// a different producer. The claim is therefore unverifiable here, not wrong.
var externalCliErrorClaims = map[string]string{
	"invalid_payload": "the heartbeat handler's error string in the TopsailAI business CLI, not a provider code",
}

// catalogCountClaim is one numeric statement about the shipped catalog together
// with the value computed from the catalog file.
type catalogCountClaim struct {
	// pattern captures the stated number in its first group.
	pattern *regexp.Regexp
	// noun names what the number is supposed to count, for the failure message.
	noun string
	// expected computes the real value from the parsed catalog.
	expected func(counts controlActionCatalogCounts) int
}

// controlActionCatalogCounts holds the counts the reference states.
type controlActionCatalogCounts struct {
	// actions is the number of entries in the catalog.
	actions int
	// instructionShortcuts is the number of entries that pin an instruction with
	// payload_constants.
	instructionShortcuts int
	// shortcutEntries is the number of dotted entries that are not instruction
	// shortcuts, which is how the document counts the plain copies.
	shortcutEntries int
}

// catalogCountClaims are the numeric statements this document makes about the
// shipped catalog. Each one is recomputed from the file rather than trusted.
var catalogCountClaims = []catalogCountClaim{
	{
		pattern:  regexp.MustCompile(`defines (\d+) actions`),
		noun:     "actions",
		expected: func(counts controlActionCatalogCounts) int { return counts.actions },
	},
	{
		pattern:  regexp.MustCompile(`(\d+) are instruction shortcuts`),
		noun:     "instruction shortcuts",
		expected: func(counts controlActionCatalogCounts) int { return counts.instructionShortcuts },
	},
	{
		pattern:  regexp.MustCompile(`carries (\d+) shortcut entries`),
		noun:     "shortcut entries",
		expected: func(counts controlActionCatalogCounts) int { return counts.shortcutEntries },
	},
}

// TestControlActionReferenceNamesOnlyCodesTheProviderEmits fails when the catalog
// reference attributes a rejection to a code the provider cannot produce.
//
// The codes are read out of the provider source by providerErrorCodes, which
// resolves the literals returned by errorCode plus every codedError site with its
// constant. Writing the set here instead would make the guard agree with itself,
// which is exactly how control_payload_conflict survived in the prose after the
// code that emitted it was deleted.
func TestControlActionReferenceNamesOnlyCodesTheProviderEmits(t *testing.T) {
	root := repoRoot(t)
	emitted := providerErrorCodes(t, root)
	if len(emitted) == 0 {
		t.Fatalf("no provider error code was found, so this guard checked nothing")
	}

	text := readRepoFile(t, root, controlActionReferenceFile)
	if strings.TrimSpace(text) == "" {
		t.Fatalf("%s is empty, so this guard checked nothing", controlActionReferenceFile)
	}

	attributed := 0
	excluded := 0
	for _, match := range rejectionAttribution.FindAllStringSubmatchIndex(text, -1) {
		code := text[match[2]:match[3]]
		line := lineAt(text, match[0])
		attributed++
		if reason, ok := externalCliErrorClaims[code]; ok {
			excluded++
			t.Logf("%s:%d attributes %s to the business CLI, not the provider: %s", controlActionReferenceFile, line, code, reason)
			continue
		}
		if _, ok := emitted[code]; !ok {
			t.Errorf("%s:%d attributes a rejection to %s, which the provider never emits, so an operator looks for a code that cannot appear; the provider emits %s", controlActionReferenceFile, line, code, strings.Join(sortedKeys(emitted), ", "))
		}
	}
	if attributed == 0 {
		t.Fatalf("no rejection in %s names an error code, so this guard checked nothing", controlActionReferenceFile)
	}
	if excluded == attributed {
		t.Fatalf("every attributed code in %s was excluded as a business CLI claim, so this guard checked nothing against the provider", controlActionReferenceFile)
	}
}

// TestControlActionReferenceStatesTheCatalogCounts fails when a number the
// reference states about the shipped catalog differs from the catalog file.
//
// The counts are parsed from conf/control-actions.conf.example, because a number
// copied into prose drifts from the file it describes. The document said the
// catalog "pins 28 instructions" while the file held 48 actions and 28 instruction
// shortcuts, so the sentence attached the shortcut count to the wrong noun.
func TestControlActionReferenceStatesTheCatalogCounts(t *testing.T) {
	root := repoRoot(t)
	counts := parseControlActionCatalog(t, root)
	if counts.actions == 0 {
		t.Fatalf("%s parsed to zero actions, so this guard checked nothing", controlActionCatalogFile)
	}

	text := readRepoFile(t, root, controlActionReferenceFile)
	if strings.TrimSpace(text) == "" {
		t.Fatalf("%s is empty, so this guard checked nothing", controlActionReferenceFile)
	}

	checked := 0
	for _, claim := range catalogCountClaims {
		matches := claim.pattern.FindAllStringSubmatchIndex(text, -1)
		if len(matches) == 0 {
			t.Fatalf("%s states no %s count, so this guard checked nothing for that claim", controlActionReferenceFile, claim.noun)
		}
		want := claim.expected(counts)
		for _, match := range matches {
			raw := text[match[2]:match[3]]
			stated, err := strconv.Atoi(raw)
			if err != nil {
				t.Fatalf("%s:%d states %q as a %s count, which is not a number: %v", controlActionReferenceFile, lineAt(text, match[0]), raw, claim.noun, err)
			}
			checked++
			if stated != want {
				t.Errorf("%s:%d states %d %s, but %s holds %d, so the number an operator plans against is wrong", controlActionReferenceFile, lineAt(text, match[0]), stated, claim.noun, controlActionCatalogFile, want)
			}
		}
	}
	if checked == 0 {
		t.Fatalf("no catalog count in %s was checked, so this guard checked nothing", controlActionReferenceFile)
	}
}

// parseControlActionCatalog reads the shipped catalog and counts what the
// reference states about it.
//
// The file is JSON with whole-line `#` comments, which the provider strips before
// parsing, so the same stripping happens here. Reading the file rather than a
// literal keeps the guard from agreeing with a stale copy of the catalog.
func parseControlActionCatalog(t *testing.T, root string) controlActionCatalogCounts {
	t.Helper()
	raw := readRepoFile(t, root, controlActionCatalogFile)
	kept := make([]string, 0, len(raw))
	for _, line := range strings.Split(raw, "\n") {
		if strings.HasPrefix(strings.TrimSpace(line), "#") {
			continue
		}
		kept = append(kept, line)
	}
	var document struct {
		Actions []struct {
			Name             string          `json:"name"`
			Command          []string        `json:"command"`
			PayloadConstants json.RawMessage `json:"payload_constants"`
		} `json:"actions"`
	}
	if err := json.Unmarshal([]byte(strings.Join(kept, "\n")), &document); err != nil {
		t.Fatalf("parse %s: %v", controlActionCatalogFile, err)
	}

	counts := controlActionCatalogCounts{actions: len(document.Actions)}
	for _, action := range document.Actions {
		if len(action.PayloadConstants) > 0 {
			counts.instructionShortcuts++
			continue
		}
		// A plain shortcut is a dotted entry that copies a target's command
		// without pinning a constant. It is counted by its shape, not by whether
		// its command still matches the target: a copy that has drifted is still a
		// shortcut entry, and TestShippedCatalogKeepsShortcutCopiesIdentical is the
		// guard that reports the drift. Counting only identical copies here would
		// make a drifted copy vanish from the count instead of being reported.
		if strings.Contains(action.Name, ".") {
			counts.shortcutEntries++
		}
	}
	return counts
}

// TestParseControlActionCatalogFindsTheShippedEntries proves the parser reads the
// real file rather than an empty document, so the count guard cannot pass by
// counting nothing.
func TestParseControlActionCatalogFindsTheShippedEntries(t *testing.T) {
	root := repoRoot(t)
	counts := parseControlActionCatalog(t, root)
	if counts.actions == 0 {
		t.Fatalf("%s parsed to zero actions", controlActionCatalogFile)
	}
	if counts.instructionShortcuts == 0 {
		t.Fatalf("%s parsed to zero instruction shortcuts, so the constant-pinning entries were not recognised", controlActionCatalogFile)
	}
	if counts.shortcutEntries == 0 {
		t.Fatalf("%s parsed to zero shortcut entries, so the dotted copies were not recognised", controlActionCatalogFile)
	}
	if counts.instructionShortcuts+counts.shortcutEntries > counts.actions {
		t.Fatalf("%s parsed to %d instruction shortcuts and %d shortcut entries out of %d actions, which cannot all be distinct", controlActionCatalogFile, counts.instructionShortcuts, counts.shortcutEntries, counts.actions)
	}
	path := filepath.Join(root, controlActionCatalogFile)
	if _, err := os.Stat(path); err != nil {
		t.Fatalf("stat %s: %v", path, err)
	}
}
