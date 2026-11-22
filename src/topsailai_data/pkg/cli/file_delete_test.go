package cli

import (
	"strings"
	"testing"
)

// TestFileDeleteCommand proves the delete subcommand removes one file and
// prints OK.
func TestFileDeleteCommand(t *testing.T) {
	mgr, ctx := setupFileManager(t, 0, nil)
	createObjectWithFiles(t, ctx, mgr, "demo", map[string]string{
		"demo.md":  "marker",
		"notes.md": "note body",
	})

	out := runFileCommand(t, ctx, mgr, "delete", "notes.md", "--object", "demo")
	if strings.TrimSpace(out) != "OK" {
		t.Fatalf("expected OK, got %q", out)
	}

	// The file is gone, so reading it now fails.
	err := runFileCommandError(t, ctx, mgr, "read", "notes.md", "--object", "demo")
	if err == nil {
		t.Fatal("expected the deleted file to be unreadable")
	}
}

// TestFileDeleteCommandKeepsBoundaryMarkdown proves the mandatory object
// Markdown cannot be removed through the CLI.
func TestFileDeleteCommandKeepsBoundaryMarkdown(t *testing.T) {
	mgr, ctx := setupFileManager(t, 0, nil)
	createObjectWithFiles(t, ctx, mgr, "demo", map[string]string{"demo.md": "marker"})

	err := runFileCommandError(t, ctx, mgr, "delete", "demo.md", "--object", "demo")
	if err == nil {
		t.Fatal("expected the boundary Markdown to be refused")
	}
	if !strings.Contains(err.Error(), "marks the object boundary") {
		t.Fatalf("expected boundary guidance, got %v", err)
	}

	// The boundary file is still readable.
	out := runFileCommand(t, ctx, mgr, "read", "demo.md", "--object", "demo")
	if out != "marker" {
		t.Fatalf("expected the boundary file to survive, got %q", out)
	}
}

// TestFileDeleteCommandRejectsFolder proves a folder is refused.
func TestFileDeleteCommandRejectsFolder(t *testing.T) {
	mgr, ctx := setupFileManager(t, 0, nil)
	createObjectWithFiles(t, ctx, mgr, "demo", map[string]string{
		"demo.md":    "marker",
		"notes/a.md": "note body",
	})

	err := runFileCommandError(t, ctx, mgr, "delete", "notes", "--object", "demo")
	if err == nil {
		t.Fatal("expected a folder rejection")
	}
	if !strings.Contains(err.Error(), "only files can be deleted") {
		t.Fatalf("expected folder guidance, got %v", err)
	}
}

// TestFileDeleteCommandReportsMissingFile proves an absent file is reported.
func TestFileDeleteCommandReportsMissingFile(t *testing.T) {
	mgr, ctx := setupFileManager(t, 0, nil)
	createObjectWithFiles(t, ctx, mgr, "demo", map[string]string{"demo.md": "marker"})

	err := runFileCommandError(t, ctx, mgr, "delete", "nope.md", "--object", "demo")
	if err == nil {
		t.Fatal("expected a missing file error")
	}
	if !strings.Contains(err.Error(), "object not found") {
		t.Fatalf("expected a not-found message, got %v", err)
	}
}

// TestFileDeleteCommandRejectsUnknownObject proves an unknown object id fails.
func TestFileDeleteCommandRejectsUnknownObject(t *testing.T) {
	mgr, ctx := setupFileManager(t, 0, nil)

	err := runFileCommandError(t, ctx, mgr, "delete", "x.md", "--object", "nope")
	if err == nil {
		t.Fatal("expected an unknown object error")
	}
	if !strings.Contains(err.Error(), "object not found") {
		t.Fatalf("expected a not-found message, got %v", err)
	}
}

// TestFileDeleteCommandRequiresPath proves the file path argument is mandatory.
func TestFileDeleteCommandRequiresPath(t *testing.T) {
	mgr, ctx := setupFileManager(t, 0, nil)
	createObjectWithFiles(t, ctx, mgr, "demo", map[string]string{"demo.md": "marker"})

	err := runFileCommandError(t, ctx, mgr, "delete", "--object", "demo")
	if err == nil {
		t.Fatal("expected a missing path error")
	}
	if !strings.Contains(err.Error(), "file delete") {
		t.Fatalf("expected the command name in the error, got %v", err)
	}
}
