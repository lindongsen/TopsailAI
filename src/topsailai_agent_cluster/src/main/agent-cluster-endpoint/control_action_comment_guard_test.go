package main

// The comment block in conf/node.endpoint.conf.example that explains where the
// ctl. capability family comes from makes claims about the implementation: the
// ADAPTERS document is the source, a document that names no ctl. capability
// advertises none, and CONTROL_ACTION_FILE is no longer read.
//
// A comment is not executable, so nothing fails when one of those claims stops
// being true. The operator then reads a sentence that describes a previous
// design and configures a node that cannot work, and the only symptom is a ctl.
// operation refused as unsupported long after the configuration was written.
//
// These guards read the implementation and the template instead of restating
// them. The struct field, the intersection call and the absence of the removed
// key are each read from the file that owns them, so a change to any of those
// files fails the guard rather than silently invalidating the comment.

import (
	"go/ast"
	"go/parser"
	"go/token"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// adapterDocumentCommentAnchor is the sentence the guards below assume still
// exists. If the comment is rewritten, the guard fails instead of checking a
// sentence that is no longer there.
const adapterDocumentCommentAnchor = "advertised from the ADAPTERS document above"

// controlActionKeyNeedle is the removed configuration key. It is assembled from
// two halves so this file does not itself contain the literal that
// TestNoSourceReadsTheRemovedControlActionFile searches for.
var controlActionKeyNeedle = "CONTROL_ACTION" + "_FILE"

// TestAdapterDocumentCarriesTheControlActionCapabilities pins the claim that the
// ADAPTERS document is where a ctl. capability is declared.
func TestAdapterDocumentCarriesTheControlActionCapabilities(t *testing.T) {
	root := repoRoot(t)

	// The ADAPTERS document decodes into AdapterConfig, so the field that carries
	// a ctl. capability has to exist there under the JSON name the document uses.
	source := readRepoFile(t, root, "internal/config/config.go")
	file, err := parser.ParseFile(token.NewFileSet(), "config.go", source, 0)
	if err != nil {
		t.Fatalf("parse internal/config/config.go: %v", err)
	}

	var tag string
	var sawField bool
	ast.Inspect(file, func(node ast.Node) bool {
		spec, ok := node.(*ast.TypeSpec)
		if !ok || spec.Name.Name != "AdapterConfig" {
			return true
		}
		structType, ok := spec.Type.(*ast.StructType)
		if !ok {
			return true
		}
		for _, field := range structType.Fields.List {
			if len(field.Names) != 1 || field.Names[0].Name != "Capabilities" {
				continue
			}
			sawField = true
			if field.Tag != nil {
				tag = field.Tag.Value
			}
		}
		return false
	})
	if !sawField {
		t.Fatalf("internal/config/config.go AdapterConfig has no Capabilities field, so the ADAPTERS document cannot be the source of a ctl. capability")
	}
	if !strings.Contains(tag, `json:"capabilities`) {
		t.Errorf("AdapterConfig.Capabilities carries tag %s, want a json tag named capabilities so the ADAPTERS document can declare a ctl. capability", tag)
	}

	// The configured capabilities are the allowlist, so the adapter has to pass
	// them into the intersection rather than reading a catalog of its own.
	adapterSource := readRepoFile(t, root, "internal/adapter/genericcli/adapter.go")
	adapterFile, err := parser.ParseFile(token.NewFileSet(), "adapter.go", adapterSource, 0)
	if err != nil {
		t.Fatalf("parse internal/adapter/genericcli/adapter.go: %v", err)
	}

	var callFound bool
	ast.Inspect(adapterFile, func(node ast.Node) bool {
		call, ok := node.(*ast.CallExpr)
		if !ok {
			return true
		}
		ident, ok := call.Fun.(*ast.Ident)
		if !ok || ident.Name != "intersectCapabilities" || len(call.Args) == 0 {
			return true
		}
		selector, ok := call.Args[0].(*ast.SelectorExpr)
		if !ok {
			return true
		}
		pkg, ok := selector.X.(*ast.Ident)
		if !ok {
			return true
		}
		if pkg.Name == "config" && selector.Sel.Name == "Capabilities" {
			callFound = true
		}
		return true
	})
	if !callFound {
		t.Fatalf("internal/adapter/genericcli/adapter.go does not pass config.Capabilities to intersectCapabilities, so the ADAPTERS document is no longer the allowlist for a ctl. capability")
	}
}

// TestShippedAdapterExampleAdvertisesNoControlAction pins the claim that a
// document naming no ctl. capability advertises none, which is the fail-closed
// default the shipped template relies on.
func TestShippedAdapterExampleAdvertisesNoControlAction(t *testing.T) {
	root := repoRoot(t)
	content := readRepoFile(t, root, "conf/node.endpoint.conf.example")

	if !strings.Contains(content, adapterDocumentCommentAnchor) {
		t.Fatalf("conf/node.endpoint.conf.example no longer states %q, so this guard is checking a comment that was rewritten", adapterDocumentCommentAnchor)
	}

	var adapterLine string
	for _, line := range strings.Split(content, "\n") {
		if strings.HasPrefix(line, "ADAPTERS=") {
			adapterLine = line
			break
		}
	}
	if adapterLine == "" {
		t.Fatalf("conf/node.endpoint.conf.example has no ADAPTERS assignment, so the comment above it describes a document that is not there")
	}
	if strings.Contains(adapterLine, `"capabilities"`) {
		t.Errorf("the shipped ADAPTERS example declares capabilities, but the comment above it says a document that names no ctl. capability advertises none as the fail-closed default: %s", adapterLine)
	}
}

// TestNoSourceReadsTheRemovedControlActionFile pins the claim that the removed
// key is no longer read.
func TestNoSourceReadsTheRemovedControlActionFile(t *testing.T) {
	root := repoRoot(t)
	self := "control_action_comment_guard_test.go"

	var offenders []string
	err := filepath.Walk(root, func(path string, info os.FileInfo, walkErr error) error {
		if walkErr != nil {
			return walkErr
		}
		if info.IsDir() {
			switch info.Name() {
			case ".git", ".tmp", ".task", "vendor":
				return filepath.SkipDir
			}
			return nil
		}
		if !strings.HasSuffix(path, ".go") || filepath.Base(path) == self {
			return nil
		}
		content, readErr := os.ReadFile(path)
		if readErr != nil {
			return readErr
		}
		if strings.Contains(string(content), controlActionKeyNeedle) {
			relative, relErr := filepath.Rel(root, path)
			if relErr != nil {
				relative = path
			}
			offenders = append(offenders, relative)
		}
		return nil
	})
	if err != nil {
		t.Fatalf("walk repository: %v", err)
	}
	if len(offenders) > 0 {
		t.Errorf("the comment says %s is no longer read, but these files still reference it: %v", controlActionKeyNeedle, offenders)
	}
}
