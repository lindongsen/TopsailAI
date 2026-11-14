package main

// The live manual procedure documents tell an operator to run
// tests/manual/live-tmux/start_services.py with specific flags. A flag that the
// script does not declare is not a documentation typo: argparse rejects the
// whole invocation, so the operator cannot start the cluster at all and the
// procedure they are following is unusable.
//
// The flags are read out of the script's own argparse declarations rather than
// restated here. If the script renames or drops a flag, this guard fails, which
// is the point: the document and the harness cannot drift apart without a test
// noticing.

import (
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"testing"
)

// manualHarnessScript is the harness the procedure documents invoke.
const manualHarnessScript = "tests/manual/live-tmux/start_services.py"

// manualProcedureDir holds the procedure documents that reference the harness.
const manualProcedureDir = "tests/manual/live-tmux"

// declaredFlagPattern reads one argparse flag declaration out of the script.
var declaredFlagPattern = regexp.MustCompile(`add_argument\("(--[a-z0-9-]+)"`)

// referencedFlagPattern reads a long flag out of a document line.
var referencedFlagPattern = regexp.MustCompile(`(--[a-z][a-z0-9-]*)`)

// TestManualProcedureFlagsAreDeclaredByTheHarness pins the structural fact that
// every flag a procedure document attributes to the harness is a flag the
// harness actually declares.
func TestManualProcedureFlagsAreDeclaredByTheHarness(t *testing.T) {
	root := repoRoot(t)

	script := readRepoFile(t, root, manualHarnessScript)
	declared := make(map[string]struct{})
	for _, match := range declaredFlagPattern.FindAllStringSubmatch(script, -1) {
		declared[match[1]] = struct{}{}
	}
	if len(declared) == 0 {
		t.Fatalf("%s declares no long flag, so this guard read nothing and cannot check any document", manualHarnessScript)
	}

	procedureDir := filepath.Join(root, manualProcedureDir)
	entries, err := os.ReadDir(procedureDir)
	if err != nil {
		t.Fatalf("read %s: %v", procedureDir, err)
	}

	type reference struct {
		file string
		line int
		flag string
	}
	var references []reference

	for _, entry := range entries {
		if entry.IsDir() || !strings.HasSuffix(entry.Name(), ".md") {
			continue
		}
		relative := filepath.Join(manualProcedureDir, entry.Name())
		content := readRepoFile(t, root, relative)
		for lineIndex, line := range strings.Split(content, "\n") {
			// Only a line that names the harness is a claim about the harness.
			// A flag mentioned elsewhere in the procedure belongs to the CLI or
			// to a shell command, not to this script.
			if !strings.Contains(line, "start_services.py") {
				continue
			}
			for _, match := range referencedFlagPattern.FindAllStringSubmatch(line, -1) {
				references = append(references, reference{file: relative, line: lineIndex + 1, flag: match[1]})
			}
		}
	}

	if len(references) == 0 {
		t.Fatalf("no procedure document in %s attributes a flag to %s, so this guard checked nothing", manualProcedureDir, manualHarnessScript)
	}

	for _, item := range references {
		if _, ok := declared[item.flag]; ok {
			continue
		}
		t.Errorf("%s:%d tells the operator to pass %s to %s, but the script declares no such flag", item.file, item.line, item.flag, manualHarnessScript)
	}
}
