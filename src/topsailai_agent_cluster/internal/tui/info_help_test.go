package tui

import (
	"bytes"
	"strings"
	"testing"
)

// TestInfoHelpAdvertisesProviderSections proves both help surfaces describe the
// metadata and runtime sections in their description.
//
// The assertion targets the Description line rather than the whole output,
// because the parameter list already names both sections. A whole-output
// substring check therefore passes even when the description still advertises the
// previous behaviour, which is exactly the drift this test exists to catch.
//
// The two surfaces are asserted through their own entry points, because the
// standalone surface overrides the catalog description.
func TestInfoHelpAdvertisesProviderSections(t *testing.T) {
	for _, tc := range []struct {
		name  string
		print func(*bytes.Buffer) error
	}{
		{
			name:  "interactive catalog",
			print: func(out *bytes.Buffer) error { return PrintCommandHelp(out, "info") },
		},
		{
			name:  "standalone override",
			print: func(out *bytes.Buffer) error { return PrintNonInteractiveCommandHelp(out, "info") },
		},
	} {
		t.Run(tc.name, func(t *testing.T) {
			var out bytes.Buffer
			if err := tc.print(&out); err != nil {
				t.Fatalf("print help: %v", err)
			}
			description := helpDescriptionLine(out.String())
			if description == "" {
				t.Fatalf("help has no description line: %q", out.String())
			}
			for _, want := range []string{"metadata", "runtime"} {
				if !strings.Contains(description, want) {
					t.Fatalf("description does not mention %q: %q", want, description)
				}
			}
		})
	}
}

// helpDescriptionLine returns the description line of a rendered help block, so an
// assertion can target the sentence that describes the command instead of any
// occurrence of a word in the whole block.
func helpDescriptionLine(text string) string {
	for _, line := range strings.Split(text, "\n") {
		if strings.HasPrefix(line, "Description: ") {
			return strings.TrimPrefix(line, "Description: ")
		}
	}
	return ""
}

// TestInfoHelpStatesRuntimeIsAProviderDocument proves the help describes the
// runtime section as the provider's own observation rather than as a reserved
// placeholder. The seam has a real source in the production provider, so help that
// called it unsourced would tell an operator to distrust a section that is in fact
// populated.
func TestInfoHelpStatesRuntimeIsAProviderDocument(t *testing.T) {
	var out bytes.Buffer
	if err := PrintCommandHelp(&out, "info"); err != nil {
		t.Fatalf("PrintCommandHelp: %v", err)
	}
	text := out.String()
	if strings.Contains(text, "no source yet") {
		t.Fatalf("help still states that runtime has no source: %q", text)
	}
	if !strings.Contains(text, "runtime observation") {
		t.Fatalf("help does not describe runtime as a provider observation: %q", text)
	}
	if !strings.Contains(text, "not reported") {
		t.Fatalf("help does not state what an empty runtime prints: %q", text)
	}
}

// TestInfoHelpStatesMetadataIsUncurated proves the help states the record is
// printed whole, because that is the property an operator relies on when looking
// for a field the cluster does not model.
func TestInfoHelpStatesMetadataIsUncurated(t *testing.T) {
	var out bytes.Buffer
	if err := PrintCommandHelp(&out, "info"); err != nil {
		t.Fatalf("PrintCommandHelp: %v", err)
	}
	if !strings.Contains(out.String(), "uncurated") {
		t.Fatalf("help does not state that metadata is uncurated: %q", out.String())
	}
}
