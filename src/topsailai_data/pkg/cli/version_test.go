package cli

import (
	"bytes"
	"encoding/json"
	"os"
	"strings"
	"testing"

	"github.com/topsailai/topsailai_data/pkg/version"
	"gopkg.in/yaml.v3"
)

// setVersionMetadata overrides the link-time build metadata for one test and
// restores it afterwards.
func setVersionMetadata(t *testing.T, ver, commit, buildDate string) {
	t.Helper()
	oldVersion, oldCommit, oldBuildDate := version.Version, version.Commit, version.BuildDate
	version.Version, version.Commit, version.BuildDate = ver, commit, buildDate
	t.Cleanup(func() {
		version.Version, version.Commit, version.BuildDate = oldVersion, oldCommit, oldBuildDate
	})
}

func TestVersionRequestRecognizesSupportedSpellings(t *testing.T) {
	cases := []struct {
		args []string
		want bool
	}{
		{args: []string{"version"}, want: true},
		{args: []string{"--version"}, want: true},
		{args: []string{"-v"}, want: true},
		{args: []string{"-version"}, want: true},
		{args: []string{"version", "--format", "json"}, want: true},
		{args: []string{"list"}, want: false},
		{args: []string{"help"}, want: false},
		{args: nil, want: false},
	}

	for _, tc := range cases {
		if got := VersionRequest(tc.args); got != tc.want {
			t.Fatalf("VersionRequest(%v) = %v, want %v", tc.args, got, tc.want)
		}
	}
}

func TestPrintVersionTextOutput(t *testing.T) {
	setVersionMetadata(t, "v1.2.3", "abc1234", "2026-11-22T03:10:23Z")

	var buf bytes.Buffer
	if err := PrintVersion(&buf, []string{"version"}); err != nil {
		t.Fatalf("PrintVersion: %v", err)
	}

	want := "topsailai-data v1.2.3 (commit abc1234, built 2026-11-22T03:10:23Z)\n"
	if buf.String() != want {
		t.Fatalf("output = %q, want %q", buf.String(), want)
	}
}

func TestPrintVersionDevelopmentFallback(t *testing.T) {
	setVersionMetadata(t, "", "", "")

	var buf bytes.Buffer
	if err := PrintVersion(&buf, []string{"--version"}); err != nil {
		t.Fatalf("PrintVersion: %v", err)
	}

	want := "topsailai-data dev (commit unknown)\n"
	if buf.String() != want {
		t.Fatalf("output = %q, want %q", buf.String(), want)
	}
}

func TestPrintVersionJSONOutput(t *testing.T) {
	setVersionMetadata(t, "v1.2.3", "abc1234", "2026-11-22T03:10:23Z")

	var buf bytes.Buffer
	if err := PrintVersion(&buf, []string{"version", "--format", "json"}); err != nil {
		t.Fatalf("PrintVersion: %v", err)
	}

	var got version.Info
	if err := json.Unmarshal(buf.Bytes(), &got); err != nil {
		t.Fatalf("decode json: %v\n%s", err, buf.String())
	}
	if got.Version != "v1.2.3" || got.Commit != "abc1234" || got.BuildDate != "2026-11-22T03:10:23Z" {
		t.Fatalf("unexpected json payload: %+v", got)
	}
}

func TestPrintVersionYAMLOutput(t *testing.T) {
	setVersionMetadata(t, "v1.2.3", "abc1234", "2026-11-22T03:10:23Z")

	var buf bytes.Buffer
	if err := PrintVersion(&buf, []string{"version", "--format", "yaml"}); err != nil {
		t.Fatalf("PrintVersion: %v", err)
	}

	var got version.Info
	if err := yaml.Unmarshal(buf.Bytes(), &got); err != nil {
		t.Fatalf("decode yaml: %v\n%s", err, buf.String())
	}
	if got.Version != "v1.2.3" || got.Commit != "abc1234" || got.BuildDate != "2026-11-22T03:10:23Z" {
		t.Fatalf("unexpected yaml payload: %+v", got)
	}
}

func TestPrintVersionRejectsInvalidFormat(t *testing.T) {
	setVersionMetadata(t, "v1.2.3", "abc1234", "2026-11-22T03:10:23Z")

	var buf bytes.Buffer
	err := PrintVersion(&buf, []string{"version", "--format", "xml"})
	if err == nil {
		t.Fatal("expected an error for an unsupported format")
	}
	if !strings.Contains(err.Error(), "must be text, yaml, or json") {
		t.Fatalf("unexpected error: %v", err)
	}
	if buf.Len() != 0 {
		t.Fatalf("expected no output on error, got %q", buf.String())
	}
}

func TestPrintVersionRejectsExtraArguments(t *testing.T) {
	setVersionMetadata(t, "v1.2.3", "abc1234", "2026-11-22T03:10:23Z")

	var buf bytes.Buffer
	err := PrintVersion(&buf, []string{"version", "extra"})
	if err == nil {
		t.Fatal("expected an error for an unexpected positional argument")
	}
	if !strings.Contains(err.Error(), "version:") {
		t.Fatalf("unexpected error: %v", err)
	}
}

func TestRunDispatchesVersionCommand(t *testing.T) {
	setVersionMetadata(t, "v1.2.3", "abc1234", "2026-11-22T03:10:23Z")
	mgr, _, ctx := setupManager(t)

	out := captureStdout(t, func() {
		if err := Run(ctx, mgr, []string{"version"}); err != nil {
			t.Fatalf("Run: %v", err)
		}
	})

	if !strings.Contains(out, "topsailai-data v1.2.3") {
		t.Fatalf("version output missing version: %q", out)
	}
	if !strings.Contains(out, "abc1234") {
		t.Fatalf("version output missing commit: %q", out)
	}
}

func TestRunDispatchesVersionFlag(t *testing.T) {
	setVersionMetadata(t, "v1.2.3", "abc1234", "2026-11-22T03:10:23Z")
	mgr, _, ctx := setupManager(t)

	out := captureStdout(t, func() {
		if err := Run(ctx, mgr, []string{"--version"}); err != nil {
			t.Fatalf("Run: %v", err)
		}
	})

	if !strings.Contains(out, "topsailai-data v1.2.3") {
		t.Fatalf("version output missing version: %q", out)
	}
}

func TestRunVersionDoesNotTouchTheStore(t *testing.T) {
	setVersionMetadata(t, "v1.2.3", "abc1234", "2026-11-22T03:10:23Z")
	mgr, root, ctx := setupManager(t)

	before := listRootEntries(t, root)
	out := captureStdout(t, func() {
		if err := Run(ctx, mgr, []string{"version"}); err != nil {
			t.Fatalf("Run: %v", err)
		}
	})
	after := listRootEntries(t, root)

	if !strings.Contains(out, "topsailai-data") {
		t.Fatalf("version output missing program name: %q", out)
	}
	if before != after {
		t.Fatalf("version query changed the store: before=%q after=%q", before, after)
	}
}

func TestRunVersionCommandAppearsInUsage(t *testing.T) {
	mgr, _, ctx := setupManager(t)

	out := captureStdout(t, func() {
		if err := Run(ctx, mgr, []string{"help"}); err != nil {
			t.Fatalf("Run: %v", err)
		}
	})

	if !strings.Contains(out, "version") {
		t.Fatalf("usage output missing version command: %q", out)
	}
	if !strings.Contains(out, "--version") {
		t.Fatalf("usage output missing --version note: %q", out)
	}
}

// listRootEntries returns the sorted names of the store root entries so a test
// can prove that a command did not modify the store.
func listRootEntries(t *testing.T, root string) string {
	t.Helper()
	entries, err := os.ReadDir(root)
	if err != nil {
		t.Fatalf("read store root: %v", err)
	}
	names := make([]string, 0, len(entries))
	for _, entry := range entries {
		names = append(names, entry.Name())
	}
	return strings.Join(names, ",")
}
