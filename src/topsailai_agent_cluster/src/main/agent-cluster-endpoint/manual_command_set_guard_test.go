package main

// The live manual procedure tells an operator which command words the REPL
// accepts, which aliases resolve to them and which scope each command is
// available in. Those three facts are owned by internal/tui/scope_commands.go:
// commandScopeMatrix is the single source of truth for availability and
// commandAliases is the alias registry.
//
// A manual procedure is prose, so nothing fails when it drifts. The operator then
// types a word the dispatcher does not know, or looks for a command in a scope
// that refuses it, and the only symptom is a usage error in the middle of an
// acceptance run. A documented alias that does not exist is worse than a missing
// one, because the operator believes two spellings are equivalent and concludes
// the CLI is broken when only one works.
//
// These guards read the matrix and the alias registry out of the Go source with
// go/ast and compare them against the documents, so neither side can drift
// silently. The documents are never restated as literals here: the expected set
// always comes from the implementation.
//
// This guard does not reuse manual_harness_flag_guard_test.go. That guard pins the
// flags start_services.py declares; this one pins the command words and aliases
// the REPL dispatches. Different owners, different failure modes.

import (
	"go/ast"
	"go/parser"
	"go/token"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"testing"
)

// scopeCommandSource owns the command matrix and the alias registry.
const scopeCommandSource = "internal/tui/scope_commands.go"

// liveTmuxDir holds the manual procedure documents.
const liveTmuxDir = "tests/manual/live-tmux"

// scopeRule is one row of commandScopeMatrix.
type scopeRule struct {
	Name      string
	Workspace bool
	Endpoint  bool
	Session   bool
}

// commandTruth is what the implementation actually accepts.
type commandTruth struct {
	Rules   []scopeRule
	Aliases map[string]string
}

// stringConsts collects the string constants declared in one file, so a map key
// written as an identifier resolves to the literal it stands for.
func stringConsts(file *ast.File) map[string]string {
	consts := map[string]string{}
	for _, decl := range file.Decls {
		gen, ok := decl.(*ast.GenDecl)
		if !ok || gen.Tok != token.CONST {
			continue
		}
		for _, spec := range gen.Specs {
			value, ok := spec.(*ast.ValueSpec)
			if !ok {
				continue
			}
			for index, name := range value.Names {
				if index >= len(value.Values) {
					continue
				}
				literal, ok := value.Values[index].(*ast.BasicLit)
				if !ok || literal.Kind != token.STRING {
					continue
				}
				text, err := strconv.Unquote(literal.Value)
				if err != nil {
					continue
				}
				consts[name.Name] = text
			}
		}
	}
	return consts
}

// compositeFor returns the composite literal assigned to the named package-level
// variable.
func compositeFor(file *ast.File, name string) (*ast.CompositeLit, bool) {
	for _, decl := range file.Decls {
		gen, ok := decl.(*ast.GenDecl)
		if !ok || gen.Tok != token.VAR {
			continue
		}
		for _, spec := range gen.Specs {
			value, ok := spec.(*ast.ValueSpec)
			if !ok {
				continue
			}
			for index, ident := range value.Names {
				if ident.Name != name || index >= len(value.Values) {
					continue
				}
				literal, ok := value.Values[index].(*ast.CompositeLit)
				if ok {
					return literal, true
				}
			}
		}
	}
	return nil, false
}

// loadCommandTruth reads the matrix and the alias registry from the source that
// owns them.
func loadCommandTruth(t *testing.T) commandTruth {
	t.Helper()
	root := repoRoot(t)
	source := readRepoFile(t, root, scopeCommandSource)
	file, err := parser.ParseFile(token.NewFileSet(), scopeCommandSource, source, 0)
	if err != nil {
		t.Fatalf("parse %s: %v", scopeCommandSource, err)
	}

	matrix, ok := compositeFor(file, "commandScopeMatrix")
	if !ok {
		t.Fatalf("%s declares no commandScopeMatrix, so this guard checked nothing", scopeCommandSource)
	}

	var rules []scopeRule
	for _, element := range matrix.Elts {
		row, ok := element.(*ast.CompositeLit)
		if !ok {
			continue
		}
		var rule scopeRule
		for _, field := range row.Elts {
			pair, ok := field.(*ast.KeyValueExpr)
			if !ok {
				continue
			}
			key, ok := pair.Key.(*ast.Ident)
			if !ok {
				continue
			}
			switch key.Name {
			case "Name":
				if literal, ok := pair.Value.(*ast.BasicLit); ok && literal.Kind == token.STRING {
					rule.Name, _ = strconv.Unquote(literal.Value)
				}
			case "Workspace", "Endpoint", "Session":
				enabled := false
				if ident, ok := pair.Value.(*ast.Ident); ok {
					enabled = ident.Name == "true"
				}
				switch key.Name {
				case "Workspace":
					rule.Workspace = enabled
				case "Endpoint":
					rule.Endpoint = enabled
				case "Session":
					rule.Session = enabled
				}
			}
		}
		if rule.Name != "" {
			rules = append(rules, rule)
		}
	}
	if len(rules) == 0 {
		t.Fatalf("%s has an empty commandScopeMatrix, so this guard checked nothing", scopeCommandSource)
	}

	registry, ok := compositeFor(file, "commandAliases")
	if !ok {
		t.Fatalf("%s declares no commandAliases, so this guard checked nothing", scopeCommandSource)
	}
	consts := stringConsts(file)
	aliases := map[string]string{}
	for _, element := range registry.Elts {
		pair, ok := element.(*ast.KeyValueExpr)
		if !ok {
			continue
		}
		var spelling string
		switch key := pair.Key.(type) {
		case *ast.BasicLit:
			if key.Kind == token.STRING {
				spelling, _ = strconv.Unquote(key.Value)
			}
		case *ast.Ident:
			spelling = consts[key.Name]
		}
		target := ""
		if literal, ok := pair.Value.(*ast.BasicLit); ok && literal.Kind == token.STRING {
			target, _ = strconv.Unquote(literal.Value)
		}
		if spelling != "" && target != "" {
			aliases[spelling] = target
		}
	}
	if len(aliases) == 0 {
		t.Fatalf("%s has an empty commandAliases registry, so this guard checked nothing", scopeCommandSource)
	}

	return commandTruth{Rules: rules, Aliases: aliases}
}

// canonicalNames returns the canonical command names in matrix order.
func (truth commandTruth) canonicalNames() []string {
	names := make([]string, 0, len(truth.Rules))
	for _, rule := range truth.Rules {
		names = append(names, rule.Name)
	}
	return names
}

// namesFor returns the canonical commands available in one scope, in matrix order.
func (truth commandTruth) namesFor(scope string) []string {
	var names []string
	for _, rule := range truth.Rules {
		available := false
		switch scope {
		case "workspace":
			available = rule.Workspace
		case "endpoint":
			available = rule.Endpoint
		case "session":
			available = rule.Session
		}
		if available {
			names = append(names, rule.Name)
		}
	}
	return names
}

// docLine returns the one-based line number of a byte offset.
func docLine(text string, offset int) int {
	return strings.Count(text[:offset], "\n") + 1
}

// readDoc reads one manual procedure document.
func readDoc(t *testing.T, relative string) string {
	t.Helper()
	root := repoRoot(t)
	path := filepath.Join(root, liveTmuxDir, relative)
	content, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("read %s: %v", path, err)
	}
	text := string(content)
	if strings.TrimSpace(text) == "" {
		t.Fatalf("%s is empty, so this guard checked nothing", relative)
	}
	return text
}

// splitList splits a comma separated command list and trims each entry.
func splitList(list string) []string {
	var entries []string
	for _, entry := range strings.Split(list, ",") {
		trimmed := strings.TrimSpace(entry)
		if trimmed != "" {
			entries = append(entries, trimmed)
		}
	}
	return entries
}

// compareCommandSets reports every command the document omits or invents.
func compareCommandSets(t *testing.T, document string, line int, documented, expected []string) {
	t.Helper()
	seen := map[string]bool{}
	for _, name := range documented {
		seen[name] = true
	}
	wanted := map[string]bool{}
	for _, name := range expected {
		wanted[name] = true
	}
	var missing, extra []string
	for _, name := range expected {
		if !seen[name] {
			missing = append(missing, name)
		}
	}
	for _, name := range documented {
		if !wanted[name] {
			extra = append(extra, name)
		}
	}
	sort.Strings(missing)
	sort.Strings(extra)
	if len(missing) > 0 {
		t.Errorf("%s:%d omits %s, so an operator never learns a command the CLI accepts", document, line, strings.Join(missing, ", "))
	}
	if len(extra) > 0 {
		t.Errorf("%s:%d names %s, which the CLI does not accept, so an operator types a command that fails", document, line, strings.Join(extra, ", "))
	}
}

// compareAliasSets reports every alias the document omits, invents or maps to the
// wrong canonical command.
func compareAliasSets(t *testing.T, document string, line int, documented, expected map[string]string) {
	t.Helper()
	var spellings []string
	for spelling := range documented {
		spellings = append(spellings, spelling)
	}
	sort.Strings(spellings)
	for _, spelling := range spellings {
		target, ok := expected[spelling]
		if !ok {
			t.Errorf("%s:%d documents the alias %q, which the CLI does not register, so only the canonical spelling works", document, line, spelling)
			continue
		}
		if target != documented[spelling] {
			t.Errorf("%s:%d documents %q as an alias of %q, but the CLI resolves it to %q", document, line, spelling, documented[spelling], target)
		}
	}
	var missing []string
	for spelling := range expected {
		if _, ok := documented[spelling]; !ok {
			missing = append(missing, spelling)
		}
	}
	sort.Strings(missing)
	if len(missing) > 0 {
		t.Errorf("%s:%d omits the aliases %s, so an operator never learns a shorter spelling the CLI accepts", document, line, strings.Join(missing, ", "))
	}
}

// parseAliasPairs turns "?=help, q=quit" into a map. Backticks are stripped
// because one document wraps each pair in code spans, and a spelling that keeps a
// backtick would be reported as an alias the CLI does not register.
func parseAliasPairs(list string) map[string]string {
	pairs := map[string]string{}
	for _, entry := range splitList(list) {
		parts := strings.SplitN(entry, "=", 2)
		if len(parts) != 2 {
			continue
		}
		spelling := strings.Trim(strings.TrimSpace(parts[0]), "`")
		target := strings.Trim(strings.TrimSpace(parts[1]), "`")
		if spelling == "" || target == "" {
			continue
		}
		pairs[spelling] = target
	}
	return pairs
}

// TestReadmeCommandSetMatchesTheMatrix pins the command set and the alias list in
// the procedure index against the implementation.
func TestReadmeCommandSetMatchesTheMatrix(t *testing.T) {
	truth := loadCommandTruth(t)
	text := readDoc(t, "README.md")

	const setAnchor = "The documented interactive command set is "
	setIndex := strings.Index(text, setAnchor)
	if setIndex < 0 {
		t.Fatalf("README.md has no %q sentence, so this guard checked nothing", setAnchor)
	}
	setStart := setIndex + len(setAnchor)
	const aliasAnchor = ". Aliases: "
	aliasIndex := strings.Index(text[setStart:], aliasAnchor)
	if aliasIndex < 0 {
		t.Fatalf("README.md documents no alias list after the command set, so this guard checked nothing")
	}
	documented := splitList(text[setStart : setStart+aliasIndex])
	if len(documented) == 0 {
		t.Fatalf("README.md documents an empty command set, so this guard checked nothing")
	}
	compareCommandSets(t, "README.md", docLine(text, setStart), documented, truth.canonicalNames())

	aliasStart := setStart + aliasIndex + len(aliasAnchor)
	aliasEnd := strings.Index(text[aliasStart:], ".")
	if aliasEnd < 0 {
		t.Fatalf("README.md has an unterminated alias list, so this guard checked nothing")
	}
	pairs := parseAliasPairs(text[aliasStart : aliasStart+aliasEnd])
	if len(pairs) == 0 {
		t.Fatalf("README.md documents an empty alias list, so this guard checked nothing")
	}
	compareAliasSets(t, "README.md", docLine(text, aliasStart), pairs, truth.Aliases)
}

// TestHelpScopeTablesMatchTheMatrix pins the three scope rows of HELP-01 against
// the availability each command actually declares.
func TestHelpScopeTablesMatchTheMatrix(t *testing.T) {
	truth := loadCommandTruth(t)
	text := readDoc(t, "help.md")

	for _, scope := range []string{"workspace", "endpoint", "session"} {
		rowPrefix := "| " + scope + " |"
		rowIndex := strings.Index(text, rowPrefix)
		if rowIndex < 0 {
			t.Fatalf("help.md has no %q scope row, so this guard checked nothing", scope)
		}
		rowStart := rowIndex + len(rowPrefix)
		rowEnd := strings.Index(text[rowStart:], "|")
		if rowEnd < 0 {
			t.Fatalf("help.md has an unterminated %q scope row, so this guard checked nothing", scope)
		}
		documented := splitList(text[rowStart : rowStart+rowEnd])
		if len(documented) == 0 {
			t.Fatalf("help.md documents an empty %q scope row, so this guard checked nothing", scope)
		}
		compareCommandSets(t, "help.md", docLine(text, rowStart), documented, truth.namesFor(scope))
	}
}

// TestHelpDetailedCommandListMatchesTheMatrix pins the HELP-02 enumeration, which
// tells the operator which commands to exercise one by one.
func TestHelpDetailedCommandListMatchesTheMatrix(t *testing.T) {
	truth := loadCommandTruth(t)
	text := readDoc(t, "help.md")

	const anchor = "For **each** of "
	start := strings.Index(text, anchor)
	if start < 0 {
		t.Fatalf("help.md has no %q enumeration, so this guard checked nothing", anchor)
	}
	start += len(anchor)
	const terminator = ", enter `help <command>`"
	end := strings.Index(text[start:], terminator)
	if end < 0 {
		t.Fatalf("help.md has an unterminated HELP-02 enumeration, so this guard checked nothing")
	}
	documented := splitList(text[start : start+end])
	if len(documented) == 0 {
		t.Fatalf("help.md enumerates no command in HELP-02, so this guard checked nothing")
	}
	compareCommandSets(t, "help.md", docLine(text, start), documented, truth.canonicalNames())
}

// TestHelpCommandTableMatchesTheMatrix pins the per-command table, so every
// canonical command has a row and no row describes a command that does not exist.
func TestHelpCommandTableMatchesTheMatrix(t *testing.T) {
	truth := loadCommandTruth(t)
	text := readDoc(t, "help.md")

	const header = "| Command | Required syntax/semantics |"
	headerIndex := strings.Index(text, header)
	if headerIndex < 0 {
		t.Fatalf("help.md has no per-command table header, so this guard checked nothing")
	}
	bodyStart := headerIndex + len(header)
	const nextSection = "\n## HELP-03"
	bodyEnd := strings.Index(text[bodyStart:], nextSection)
	if bodyEnd < 0 {
		t.Fatalf("help.md has no HELP-03 heading after the per-command table, so this guard checked nothing")
	}
	body := text[bodyStart : bodyStart+bodyEnd]

	var documented []string
	offset := 0
	for {
		rowIndex := strings.Index(body[offset:], "\n| ")
		if rowIndex < 0 {
			break
		}
		rowStart := offset + rowIndex + len("\n| ")
		rowEnd := strings.Index(body[rowStart:], " |")
		if rowEnd < 0 {
			break
		}
		name := strings.TrimSpace(body[rowStart : rowStart+rowEnd])
		offset = rowStart + rowEnd
		if name == "" || strings.HasPrefix(name, "---") {
			continue
		}
		documented = append(documented, name)
	}
	if len(documented) == 0 {
		t.Fatalf("help.md has no per-command table row, so this guard checked nothing")
	}
	compareCommandSets(t, "help.md", docLine(text, bodyStart), documented, truth.canonicalNames())
}

// TestHelpGlobalHelpStatesTheCountsAndAliases pins the HELP-03 sentence that states
// how many canonical commands and how many aliases `help all` must show.
func TestHelpGlobalHelpStatesTheCountsAndAliases(t *testing.T) {
	truth := loadCommandTruth(t)
	text := readDoc(t, "help.md")

	const countAnchor = "Expect all "
	countIndex := strings.Index(text, countAnchor)
	if countIndex < 0 {
		t.Fatalf("help.md has no %q sentence, so this guard checked nothing", countAnchor)
	}
	countStart := countIndex + len(countAnchor)
	const countTerminator = " canonical commands"
	countEnd := strings.Index(text[countStart:], countTerminator)
	if countEnd < 0 {
		t.Fatalf("help.md has an unterminated canonical command count, so this guard checked nothing")
	}
	stated, err := strconv.Atoi(strings.TrimSpace(text[countStart : countStart+countEnd]))
	if err != nil {
		t.Fatalf("help.md states a non-numeric canonical command count %q: %v", text[countStart:countStart+countEnd], err)
	}
	if stated != len(truth.Rules) {
		t.Errorf("help.md:%d states %d canonical commands, but commandScopeMatrix declares %d", docLine(text, countStart), stated, len(truth.Rules))
	}

	const aliasAnchor = "aliases (`"
	aliasIndex := strings.Index(text[countStart:], aliasAnchor)
	if aliasIndex < 0 {
		t.Fatalf("help.md states no alias list in HELP-03, so this guard checked nothing")
	}
	aliasStart := countStart + aliasIndex + len(aliasAnchor)
	aliasEnd := strings.Index(text[aliasStart:], "`)")
	if aliasEnd < 0 {
		t.Fatalf("help.md has an unterminated alias list in HELP-03, so this guard checked nothing")
	}
	pairs := parseAliasPairs(text[aliasStart : aliasStart+aliasEnd])
	if len(pairs) == 0 {
		t.Fatalf("help.md states an empty alias list in HELP-03, so this guard checked nothing")
	}
	compareAliasSets(t, "help.md", docLine(text, aliasStart), pairs, truth.Aliases)
}

// TestFailuresProcedureNamesOnlyKnownCommands pins the ERR-01 procedure, which
// tells the operator which commands to try in a scope that must refuse them. Two
// separate mistakes make the case prove nothing: a word the dispatcher does not
// know produces a different error, and a command that the named scopes actually
// allow produces no refusal at all, so the operator records a PASS for a check
// that never ran. Both are checked against the matrix rather than restated here.
func TestFailuresProcedureNamesOnlyKnownCommands(t *testing.T) {
	truth := loadCommandTruth(t)
	text := readDoc(t, "failures.md")

	const rowPrefix = "| ERR-01 |"
	rowIndex := strings.Index(text, rowPrefix)
	if rowIndex < 0 {
		t.Fatalf("failures.md has no ERR-01 row, so this guard checked nothing")
	}
	rowStart := rowIndex + len(rowPrefix)
	rowEnd := strings.Index(text[rowStart:], "|")
	if rowEnd < 0 {
		t.Fatalf("failures.md has an unterminated ERR-01 row, so this guard checked nothing")
	}
	procedure := text[rowStart : rowStart+rowEnd]

	known := map[string]bool{}
	for _, name := range truth.canonicalNames() {
		known[name] = true
	}
	for spelling := range truth.Aliases {
		known[spelling] = true
	}

	checked := 0
	for _, entry := range splitList(procedure) {
		words := strings.Fields(entry)
		if len(words) == 0 {
			continue
		}
		// The first entry names the scopes before the command, so the command word
		// is the last one.
		word := words[len(words)-1]
		checked++
		canonical := word
		if target, ok := truth.Aliases[word]; ok {
			canonical = target
		}
		if !known[word] {
			t.Errorf("failures.md:%d names %q in the ERR-01 procedure, but the CLI accepts neither that command nor that alias, so the case proves nothing about scope refusal", docLine(text, rowStart), word)
			continue
		}
		// The row names workspace and endpoint as the scopes that must refuse these
		// commands, so a command either scope allows cannot demonstrate a refusal.
		for _, scope := range []string{"workspace", "endpoint"} {
			for _, available := range truth.namesFor(scope) {
				if available != canonical {
					continue
				}
				t.Errorf("failures.md:%d names %q in the ERR-01 procedure, but %s scope allows it, so the case records a refusal that never happens", docLine(text, rowStart), word, scope)
				break
			}
		}
	}
	if checked == 0 {
		t.Fatalf("failures.md ERR-01 procedure names no command, so this guard checked nothing")
	}
}
