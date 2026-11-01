package tui

import (
	"context"
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

func TestInteractiveContinuesAfterRecoveredCommandFailure(t *testing.T) {
	stub := &interactiveStub{endpoints: []protocol.Endpoint{{EndpointID: "endpoint-1"}}, reports: map[string]protocol.InventoryReport{"endpoint-1": testInventory()}, failList: true}
	var output, errorsOut strings.Builder
	if err := RunInteractive(context.Background(), stub, strings.NewReader("list\nhelp\nquit\n"), &output, &errorsOut, InteractiveOptions{}); err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(errorsOut.String(), "temporary list failure") {
		t.Fatalf("missing recovered failure: %q", errorsOut.String())
	}
	if !strings.Contains(output.String(), "commands:") {
		t.Fatalf("loop did not continue to help: %q", output.String())
	}
}

func TestInteractiveExitAliasesReturnAfterPrompt(t *testing.T) {
	for _, command := range []string{"quit\n", "exit\n", ""} {
		var output, errorsOut strings.Builder
		if err := RunInteractive(context.Background(), &interactiveStub{}, strings.NewReader(command), &output, &errorsOut, InteractiveOptions{}); err != nil {
			t.Fatalf("command %q: %v", command, err)
		}
	}
}

func TestSafeWriterDoesNotLeakControlsAcrossWrites(t *testing.T) {
	var output strings.Builder
	writer := newSafeWriter(&output)
	if _, err := writer.Write([]byte("prefix\x1b")); err != nil {
		t.Fatal(err)
	}
	if _, err := writer.Write([]byte("[31msecret\r\n")); err != nil {
		t.Fatal(err)
	}
	if strings.ContainsAny(output.String(), "\x1b\r") {
		t.Fatalf("control sequence leaked across writes: %q", output.String())
	}
}
