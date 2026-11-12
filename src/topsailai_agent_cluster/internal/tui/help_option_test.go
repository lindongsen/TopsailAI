package tui

import (
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

// TestInteractivePayloadCommandsTreatHelpAsLiteralText pins the boundary between
// the two help surfaces. In the REPL, send and btw take the rest of the line as
// literal content, so "--help" is a message, not a help request: an operator who
// wants help types "help send". Only the standalone CLI answers --help, because
// there the command word and the payload are separated by argv positions.
func TestInteractivePayloadCommandsTreatHelpAsLiteralText(t *testing.T) {
	for _, command := range []string{"send", "btw"} {
		t.Run(command, func(t *testing.T) {
			stub := &interactiveStub{
				endpoints: []protocol.Endpoint{{EndpointID: "endpoint-1"}},
				reports:   map[string]protocol.InventoryReport{"endpoint-1": testInventory()},
			}
			input := "cd endpoint-1/session-1\n" + command + " --help\nquit\n"
			_, diagnostics := runScope(t, stub, input, ColorPolicy{})
			if stub.admit != 1 {
				t.Fatalf("%s --help admitted %d commands, want 1; diagnostics=%q", command, stub.admit, diagnostics)
			}
			if strings.Contains(diagnostics, "Syntax:") || strings.Contains(diagnostics, "Description:") {
				t.Fatalf("%s --help rendered help instead of sending literal text: %q", command, diagnostics)
			}
			payload := string(stub.intents[0].Payload)
			if !strings.Contains(payload, "--help") {
				t.Fatalf("%s payload=%q does not carry the literal --help text", command, payload)
			}
		})
	}
}

// TestInteractiveHelpStaysTheOnlyHelpEntry proves the REPL keeps one help entry,
// so the payload commands above never need a --help exception.
func TestInteractiveHelpStaysTheOnlyHelpEntry(t *testing.T) {
	stub := &interactiveStub{
		endpoints: []protocol.Endpoint{{EndpointID: "endpoint-1"}},
		reports:   map[string]protocol.InventoryReport{"endpoint-1": testInventory()},
	}
	output, _ := runScope(t, stub, "help send\nquit\n", ColorPolicy{})
	if !strings.Contains(output, "Syntax:") || !strings.Contains(output, "send [text]") {
		t.Fatalf("help send did not render the interactive detail: %q", output)
	}
}

// TestInteractiveHelpStatesThePayloadCommandsAcceptNoOptions pins the explicit
// exception the operator needs to see. The REPL takes the rest of the line as
// literal content for send and btw, so neither accepts any option; the help text
// must say so instead of leaving the operator to discover it by sending "--help"
// as a message. The standalone surface keeps --help, so the same entry must not
// carry this line there.
func TestInteractiveHelpStatesThePayloadCommandsAcceptNoOptions(t *testing.T) {
	for _, command := range []string{"send", "btw"} {
		t.Run(command, func(t *testing.T) {
			stub := &interactiveStub{
				endpoints: []protocol.Endpoint{{EndpointID: "endpoint-1"}},
				reports:   map[string]protocol.InventoryReport{"endpoint-1": testInventory()},
			}
			output, _ := runScope(t, stub, "help "+command+"\nquit\n", ColorPolicy{})
			if !strings.Contains(output, "no options:") {
				t.Fatalf("help %s does not state the no-options exception: %q", command, output)
			}
			if !strings.Contains(output, command+" --help sends the text --help") {
				t.Fatalf("help %s does not explain that --help is literal text: %q", command, output)
			}
		})
	}
}

// TestStandaloneHelpKeepsTheHelpOption proves the exception stays interactive-only.
// The standalone command separates the command word from the payload by argv
// position, so it keeps --help and must not advertise the REPL restriction.
func TestStandaloneHelpKeepsTheHelpOption(t *testing.T) {
	for _, command := range []string{"send", "btw"} {
		t.Run(command, func(t *testing.T) {
			var out strings.Builder
			if err := PrintNonInteractiveCommandHelp(&out, command); err != nil {
				t.Fatalf("PrintNonInteractiveCommandHelp(%q): %v", command, err)
			}
			if strings.Contains(out.String(), "no options:") {
				t.Fatalf("standalone help %s advertises the interactive-only exception: %q", command, out.String())
			}
		})
	}
}
