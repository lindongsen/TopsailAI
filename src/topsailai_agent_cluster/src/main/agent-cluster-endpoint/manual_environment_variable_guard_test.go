package main

import (
	"go/ast"
	"go/parser"
	"go/token"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"testing"
)

// environmentDocument is the manual procedure whose environment claims this
// guard pins. It is the only manual document that names environment variables.
const environmentDocument = "tests/manual/live-tmux/environment.md"

// cliPackageDir holds the process boundary that resolves every environment
// variable. Nothing below it reads the environment, so this directory is the
// complete surface a manual procedure may name.
const cliPackageDir = "src/main/agent-cluster-cli"

// backtickedToken matches one backticked span in the document. The manual
// documents wrap every literal value in backticks, so the span is the unit a
// reader treats as a name rather than prose.
var backtickedToken = regexp.MustCompile("`([^`\n]+)`")

// environmentName matches a token shaped like an environment variable name.
// It deliberately requires an uppercase first letter and at least one more
// character, so a backticked command word such as `list` is not mistaken for a
// variable and a single letter is not either.
var environmentName = regexp.MustCompile(`^[A-Z][A-Z0-9_]+$`)

// cliEnvironmentNames returns every environment variable name the operator CLI
// can read. Two shapes are collected because the package uses both: a direct
// os.Getenv or os.LookupEnv call, and a package constant whose identifier ends
// in Env and is passed to the injected lookup function. Collecting only the
// first shape would report a correctly documented AGENT_CLUSTER_CLI_* variable
// as unknown, so both are read from the source rather than listed here.
func cliEnvironmentNames(t *testing.T, root string) map[string]struct{} {
	t.Helper()
	dir := filepath.Join(root, cliPackageDir)
	entries, err := os.ReadDir(dir)
	if err != nil {
		t.Fatalf("read %s: %v", dir, err)
	}

	names := map[string]struct{}{}
	parsed := 0
	files := token.NewFileSet()
	for _, entry := range entries {
		name := entry.Name()
		if entry.IsDir() || !strings.HasSuffix(name, ".go") || strings.HasSuffix(name, "_test.go") {
			continue
		}
		file, err := parser.ParseFile(files, filepath.Join(dir, name), nil, 0)
		if err != nil {
			t.Fatalf("parse %s: %v", name, err)
		}
		parsed++
		ast.Inspect(file, func(node ast.Node) bool {
			switch typed := node.(type) {
			case *ast.CallExpr:
				selector, ok := typed.Fun.(*ast.SelectorExpr)
				if !ok || len(typed.Args) != 1 {
					return true
				}
				pkg, ok := selector.X.(*ast.Ident)
				if !ok || pkg.Name != "os" {
					return true
				}
				if selector.Sel.Name != "Getenv" && selector.Sel.Name != "LookupEnv" {
					return true
				}
				if literal, ok := typed.Args[0].(*ast.BasicLit); ok && literal.Kind == token.STRING {
					if value, err := strconv.Unquote(literal.Value); err == nil {
						names[value] = struct{}{}
					}
				}
			case *ast.ValueSpec:
				for index, identifier := range typed.Names {
					if !strings.HasSuffix(identifier.Name, "Env") || index >= len(typed.Values) {
						continue
					}
					literal, ok := typed.Values[index].(*ast.BasicLit)
					if !ok || literal.Kind != token.STRING {
						continue
					}
					if value, err := strconv.Unquote(literal.Value); err == nil {
						names[value] = struct{}{}
					}
				}
			}
			return true
		})
	}
	if parsed == 0 {
		t.Fatalf("%s holds no non-test Go file, so this guard read no environment variable", cliPackageDir)
	}
	if len(names) == 0 {
		t.Fatalf("%s declares no environment variable name, so this guard checked nothing", cliPackageDir)
	}
	return names
}

// documentedEnvironmentNames returns every environment variable name the manual
// document names, together with the line it appears on, so a failure points at
// the sentence a tester would follow.
func documentedEnvironmentNames(t *testing.T, text string) map[string]int {
	t.Helper()
	found := map[string]int{}
	for _, match := range backtickedToken.FindAllStringSubmatchIndex(text, -1) {
		token := text[match[2]:match[3]]
		if !environmentName.MatchString(token) {
			continue
		}
		if _, seen := found[token]; !seen {
			found[token] = lineAt(text, match[0])
		}
	}
	return found
}

// TestEnvironmentDocumentNamesOnlyVariablesTheCliReads pins the structural fact
// that every environment variable the manual procedure tells a tester to set is
// one the operator CLI actually reads. A name the CLI never reads sends the
// tester to export a variable that changes nothing, and the case then records a
// behaviour the environment cannot produce.
func TestEnvironmentDocumentNamesOnlyVariablesTheCliReads(t *testing.T) {
	root := repoRoot(t)
	text := readRepoFile(t, root, environmentDocument)
	if strings.TrimSpace(text) == "" {
		t.Fatalf("%s is empty, so this guard checked nothing", environmentDocument)
	}

	documented := documentedEnvironmentNames(t, text)
	if len(documented) == 0 {
		t.Fatalf("%s names no environment variable, so this guard checked nothing", environmentDocument)
	}
	if _, ok := documented["NO_COLOR"]; !ok {
		t.Fatalf("%s no longer names NO_COLOR, so the colour claim lost the variable it depends on", environmentDocument)
	}

	known := cliEnvironmentNames(t, root)
	names := make([]string, 0, len(documented))
	for name := range documented {
		names = append(names, name)
	}
	sort.Strings(names)

	for _, name := range names {
		if _, ok := known[name]; ok {
			continue
		}
		t.Errorf("%s:%d names %s, which the operator CLI never reads, so a tester exports a variable that changes nothing; the CLI reads %s",
			environmentDocument, documented[name], name, strings.Join(sortedKeys(known), ", "))
	}
}

// TestEnvironmentDocumentStatesTheDumbTerminalEffect pins the structural fact
// that the manual procedure tells a tester what a dumb terminal does, because
// the CLI disables both colour and the line editor for it. A tester who runs the
// audit in a dumb terminal sees SESSION_STATUS appear and loses arrow-key recall,
// so a document that stays silent makes both observations look like defects.
func TestEnvironmentDocumentStatesTheDumbTerminalEffect(t *testing.T) {
	root := repoRoot(t)
	text := readRepoFile(t, root, environmentDocument)
	if strings.TrimSpace(text) == "" {
		t.Fatalf("%s is empty, so this guard checked nothing", environmentDocument)
	}

	documented := documentedEnvironmentNames(t, text)
	line, ok := documented["TERM"]
	if !ok {
		t.Fatalf("%s names no TERM, but the CLI disables colour and the line editor when TERM is dumb, so a tester in a dumb terminal reports both as defects", environmentDocument)
	}
	if !strings.Contains(text, "dumb") {
		t.Fatalf("%s:%d names TERM without saying which value changes behaviour, so a tester cannot act on it", environmentDocument, line)
	}
	if !strings.Contains(text, "line editor") {
		t.Fatalf("%s:%d names TERM without saying the line editor is lost, so a tester reports the missing recall as a defect", environmentDocument, line)
	}

	// The premise is checked in the source rather than assumed, so a change that
	// stops disabling the editor for a dumb terminal fails here instead of
	// leaving the document describing behaviour the CLI no longer has.
	if !dumbTerminalDisablesEditor(t, root) {
		t.Fatalf("%s:%d states that a dumb terminal loses the line editor, but %s no longer disables it, so the document describes behaviour the CLI does not have",
			environmentDocument, line, filepath.Join(cliPackageDir, "terminal.go"))
	}
}

// dumbTerminalDisablesEditor reports whether interactiveEditor refuses the
// terminal editor when TERM is dumb. It reads the function body rather than the
// whole file, so an unrelated TERM comparison elsewhere cannot satisfy it.
func dumbTerminalDisablesEditor(t *testing.T, root string) bool {
	t.Helper()
	path := filepath.Join(root, cliPackageDir, "terminal.go")
	file, err := parser.ParseFile(token.NewFileSet(), path, nil, 0)
	if err != nil {
		t.Fatalf("parse %s: %v", path, err)
	}

	found := false
	for _, declaration := range file.Decls {
		function, ok := declaration.(*ast.FuncDecl)
		if !ok || function.Name.Name != "interactiveEditor" || function.Body == nil {
			continue
		}
		ast.Inspect(function.Body, func(node ast.Node) bool {
			call, ok := node.(*ast.CallExpr)
			if !ok || len(call.Args) != 1 {
				return true
			}
			selector, ok := call.Fun.(*ast.SelectorExpr)
			if !ok || selector.Sel.Name != "Getenv" {
				return true
			}
			pkg, ok := selector.X.(*ast.Ident)
			if !ok || pkg.Name != "os" {
				return true
			}
			literal, ok := call.Args[0].(*ast.BasicLit)
			if !ok || literal.Kind != token.STRING {
				return true
			}
			if value, err := strconv.Unquote(literal.Value); err == nil && value == "TERM" {
				found = true
			}
			return true
		})
	}
	return found
}
