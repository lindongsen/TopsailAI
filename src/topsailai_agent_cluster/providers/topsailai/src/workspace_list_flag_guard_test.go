package main

import (
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
	"testing"
)

// TestWorkspaceListFlagsAreRegisteredByTheProvider proves every flag this
// executable sends on a `workspace list` argv is a flag the provider CLI
// actually registers.
//
// The defect this guards against is silent in both directions. The provider
// parses with `parse_known_args`, so an unregistered flag is discarded without
// an error, without a stderr line and with exit status 0. The provider therefore
// looks healthy while the document it returns lacks the field the flag was meant
// to add, and the Cluster reports a provider that "did not report" a value it was
// never asked for.
//
// That is not hypothetical. `--include-runtime` was added to three call sites
// here while the `ai-dev` container still ran a provider checkout that predated
// the flag's registration. Every row on that node reported
// "provider did not report runtime message counts" and the MESSAGE column stayed
// empty, while the Endpoint reported the inventory as `ok`. See
// `issues/message-counts-empty-on-older-provider.md`.
//
// The check reads the sibling provider source instead of invoking the CLI, so it
// is deterministic and needs no live provider installation. It proves the flags
// this executable sends are registered by the provider source in this repository;
// it cannot prove that a deployed node runs a checkout containing that
// registration, because that is a deployment property. The deployment check
// belongs to the release notes, and this guard is what keeps the code side honest.
func TestWorkspaceListFlagsAreRegisteredByTheProvider(t *testing.T) {
	sent := workspaceListFlagsSentByThisExecutable(t)
	if len(sent) == 0 {
		t.Fatalf("no workspace list argv was found, so this guard would pass without checking anything")
	}

	registered := workspaceListFlagsRegisteredByTheProvider(t)

	var unregistered []string
	for _, flag := range sent {
		if !registered[flag] {
			unregistered = append(unregistered, flag)
		}
	}
	if len(unregistered) > 0 {
		t.Fatalf("this executable sends %v on a workspace list argv, but the provider does not register them; "+
			"parse_known_args discards an unknown flag with exit status 0, so the read would silently return a "+
			"document without the field the flag adds", unregistered)
	}
}

// workspaceListFlagsSentByThisExecutable collects every long flag that appears in
// a production argv slice which also names the `workspace list` subcommand.
//
// The argv is read from source rather than from a running process because the
// flags are string literals in the call sites. A slice is recognised by
// containing both "workspace" and "list" as quoted elements, which is how every
// call site spells the subcommand.
func workspaceListFlagsSentByThisExecutable(t *testing.T) []string {
	t.Helper()
	entries, err := os.ReadDir(".")
	if err != nil {
		t.Fatalf("read the package directory: %v", err)
	}
	slicePattern := regexp.MustCompile(`(?s)\[\]string\{(.*?)\}`)
	quotedPattern := regexp.MustCompile(`"([^"]*)"`)
	flagPattern := regexp.MustCompile(`^--[a-z][a-z-]*$`)

	seen := make(map[string]bool)
	for _, entry := range entries {
		name := entry.Name()
		if entry.IsDir() || !strings.HasSuffix(name, ".go") || strings.HasSuffix(name, "_test.go") {
			continue
		}
		content, err := os.ReadFile(filepath.Clean(name))
		if err != nil {
			t.Fatalf("read %s: %v", name, err)
		}
		for _, slice := range slicePattern.FindAllStringSubmatch(string(content), -1) {
			var elements []string
			for _, match := range quotedPattern.FindAllStringSubmatch(slice[1], -1) {
				elements = append(elements, match[1])
			}
			if !containsAll(elements, "workspace", "list") {
				continue
			}
			for _, element := range elements {
				if flagPattern.MatchString(element) {
					seen[element] = true
				}
			}
		}
	}

	flags := make([]string, 0, len(seen))
	for flag := range seen {
		flags = append(flags, flag)
	}
	sort.Strings(flags)
	return flags
}

// workspaceListFlagsRegisteredByTheProvider reads the provider's own subparser
// registration and returns the long flags declared on the `workspace list`
// parser.
//
// The registration is read from the `workspace_list_parser.add_argument` calls
// rather than from the whole file, because a flag registered on a sibling
// subparser is not accepted by `list`. That distinction is the same one that made
// `workspace list --all` silently return one row while `workspace --all list`
// returned eight.
func workspaceListFlagsRegisteredByTheProvider(t *testing.T) map[string]bool {
	t.Helper()
	source := siblingPath(t, "cli", "cli_topsailai", "core.py")
	content, err := os.ReadFile(source)
	if err != nil {
		t.Skipf("provider source unavailable: %v", err)
	}

	callPattern := regexp.MustCompile(`(?s)workspace_list_parser\.add_argument\((.*?)\n    \)`)
	calls := callPattern.FindAllStringSubmatch(string(content), -1)
	if len(calls) == 0 {
		t.Fatalf("no workspace_list_parser.add_argument call was found in %s, so this guard cannot check anything", source)
	}

	flagPattern := regexp.MustCompile(`"(--[a-z][a-z-]*)"`)
	registered := make(map[string]bool)
	for _, call := range calls {
		for _, match := range flagPattern.FindAllStringSubmatch(call[1], -1) {
			registered[match[1]] = true
		}
	}
	if len(registered) == 0 {
		t.Fatalf("the workspace list parser registers no long flag in %s, so this guard cannot check anything", source)
	}
	return registered
}

// containsAll reports whether every wanted element is present.
func containsAll(elements []string, wanted ...string) bool {
	present := make(map[string]bool, len(elements))
	for _, element := range elements {
		present[element] = true
	}
	for _, want := range wanted {
		if !present[want] {
			return false
		}
	}
	return true
}
