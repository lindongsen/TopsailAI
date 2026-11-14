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

// This guard exists because a manual procedure that cites a test file or an error
// code is a claim about the code, and prose keeps reading as evidence after the
// code is gone. ERR-08 cited internal/adapter/topsailai/output_envelope_test.go
// after 1e76b443 deleted that file, and CTLSHORT-01 recorded
// control_payload_conflict after the same commit removed the only site that
// emitted it. Both sentences still looked like proof.
//
// It is separate from catalog_reference_guard_test.go and
// manual_command_set_guard_test.go: those pin what the documents say about
// configuration and about the command surface, while this one pins whether the
// evidence a document points at still exists and still produces the value the
// document records.

// manualEvidenceDocuments are the manual harness documents that cite code.
var manualEvidenceDocuments = []string{
	"tests/manual/live-tmux/results.md",
	"tests/manual/live-tmux/failures.md",
}

// citedGoPath matches a backticked Go file path, which is how these documents
// name the test that covers a case.
var citedGoPath = regexp.MustCompile("`([A-Za-z0-9_./-]+\\.go)`")

// recordedErrorCode matches an error code recorded in a results table or a
// disposition paragraph. The value is either a bare identifier or a quoted
// string, because the tables write it unquoted and the prose quotes it.
var recordedErrorCode = regexp.MustCompile(`ErrorCode: ("[^"]*"|[A-Za-z0-9_]+)`)

// TestManualDocumentsCiteFilesThatExist fails when a manual document points at a
// Go file that is not on disk.
//
// A reader who follows the citation finds nothing, so a BLOCKED disposition that
// rests on "automated coverage lives in X" is unsupported. The check reads the
// filesystem rather than a list, because a list would be a second copy of the
// same fact and would drift with the citation.
func TestManualDocumentsCiteFilesThatExist(t *testing.T) {
	root := repoRoot(t)
	citations := 0
	for _, relative := range manualEvidenceDocuments {
		path := filepath.Join(root, relative)
		content, err := os.ReadFile(path)
		if err != nil {
			t.Fatalf("read %s: %v", path, err)
		}
		text := string(content)
		if strings.TrimSpace(text) == "" {
			t.Fatalf("%s is empty, so this guard checked nothing", relative)
		}
		for _, match := range citedGoPath.FindAllStringSubmatchIndex(text, -1) {
			cited := text[match[2]:match[3]]
			citations++
			line := lineAt(text, match[0])
			if _, err := os.Stat(filepath.Join(root, cited)); err != nil {
				t.Errorf("%s:%d cites %s, which does not exist, so the case it claims to cover has no evidence", relative, line, cited)
			}
		}
	}
	if citations == 0 {
		t.Fatalf("no manual document cites a Go file, so this guard checked nothing")
	}
}

// TestManualDocumentsRecordOnlyCodesTheProviderEmits fails when a manual document
// records an error code the provider cannot produce.
//
// The codes are read out of the provider source: the literals returned by
// errorCode plus every codedError site, with its constant resolved. Writing the
// set here instead would make the guard agree with itself, which is exactly how
// control_payload_conflict survived in the prose after the code that emitted it
// was deleted.
func TestManualDocumentsRecordOnlyCodesTheProviderEmits(t *testing.T) {
	root := repoRoot(t)
	emitted := providerErrorCodes(t, root)
	if len(emitted) == 0 {
		t.Fatalf("no provider error code was found, so this guard checked nothing")
	}
	recorded := 0
	for _, relative := range manualEvidenceDocuments {
		path := filepath.Join(root, relative)
		content, err := os.ReadFile(path)
		if err != nil {
			t.Fatalf("read %s: %v", path, err)
		}
		text := string(content)
		for _, match := range recordedErrorCode.FindAllStringSubmatchIndex(text, -1) {
			raw := strings.Trim(text[match[2]:match[3]], `"`)
			recorded++
			if raw == "" {
				continue
			}
			line := lineAt(text, match[0])
			if _, ok := emitted[raw]; !ok {
				t.Errorf("%s:%d records ErrorCode %s, which the provider never emits, so the recorded outcome cannot be reproduced; the provider emits %s", relative, line, raw, strings.Join(sortedKeys(emitted), ", "))
			}
		}
	}
	if recorded == 0 {
		t.Fatalf("no manual document records an error code, so this guard checked nothing")
	}
}

// providerErrorCodes collects every error code the provider can put in a
// response, read from the provider package source.
func providerErrorCodes(t *testing.T, root string) map[string]struct{} {
	t.Helper()
	dir := filepath.Join(root, "providers", "topsailai")
	entries, err := os.ReadDir(dir)
	if err != nil {
		t.Fatalf("read %s: %v", dir, err)
	}
	fset := token.NewFileSet()
	files := make([]*ast.File, 0, len(entries))
	for _, entry := range entries {
		name := entry.Name()
		if entry.IsDir() || !strings.HasSuffix(name, ".go") || strings.HasSuffix(name, "_test.go") {
			continue
		}
		parsed, err := parser.ParseFile(fset, filepath.Join(dir, name), nil, 0)
		if err != nil {
			t.Fatalf("parse %s: %v", name, err)
		}
		files = append(files, parsed)
	}
	if len(files) == 0 {
		t.Fatalf("no provider source file was parsed, so this guard checked nothing")
	}
	constants := stringConstants(files)
	codes := map[string]struct{}{}
	for _, file := range files {
		ast.Inspect(file, func(node ast.Node) bool {
			switch typed := node.(type) {
			case *ast.FuncDecl:
				if typed.Name.Name != "errorCode" {
					return true
				}
				ast.Inspect(typed.Body, func(inner ast.Node) bool {
					if literal, ok := inner.(*ast.BasicLit); ok && literal.Kind == token.STRING {
						if value, err := strconv.Unquote(literal.Value); err == nil {
							codes[value] = struct{}{}
						}
					}
					return true
				})
				return false
			case *ast.CompositeLit:
				identifier, ok := typed.Type.(*ast.Ident)
				if !ok || identifier.Name != "codedError" {
					return true
				}
				for _, element := range typed.Elts {
					pair, ok := element.(*ast.KeyValueExpr)
					if !ok {
						continue
					}
					key, ok := pair.Key.(*ast.Ident)
					if !ok || key.Name != "code" {
						continue
					}
					if value, ok := resolveString(pair.Value, constants); ok {
						codes[value] = struct{}{}
					}
				}
			}
			return true
		})
	}
	return codes
}

// stringConstants maps package-level string constant names to their values.
func stringConstants(files []*ast.File) map[string]string {
	values := map[string]string{}
	for _, file := range files {
		for _, declaration := range file.Decls {
			generic, ok := declaration.(*ast.GenDecl)
			if !ok || generic.Tok != token.CONST {
				continue
			}
			for _, spec := range generic.Specs {
				value, ok := spec.(*ast.ValueSpec)
				if !ok || len(value.Names) != 1 || len(value.Values) != 1 {
					continue
				}
				literal, ok := value.Values[0].(*ast.BasicLit)
				if !ok || literal.Kind != token.STRING {
					continue
				}
				if decoded, err := strconv.Unquote(literal.Value); err == nil {
					values[value.Names[0].Name] = decoded
				}
			}
		}
	}
	return values
}

// resolveString resolves a string literal or a named constant to its value.
func resolveString(expression ast.Expr, constants map[string]string) (string, bool) {
	switch typed := expression.(type) {
	case *ast.BasicLit:
		if typed.Kind != token.STRING {
			return "", false
		}
		value, err := strconv.Unquote(typed.Value)
		return value, err == nil
	case *ast.Ident:
		value, ok := constants[typed.Name]
		return value, ok
	}
	return "", false
}

// sortedKeys returns the map keys in a stable order so a failure message reads
// the same on every run.
func sortedKeys(values map[string]struct{}) []string {
	keys := make([]string, 0, len(values))
	for key := range values {
		keys = append(keys, key)
	}
	sort.Strings(keys)
	return keys
}
