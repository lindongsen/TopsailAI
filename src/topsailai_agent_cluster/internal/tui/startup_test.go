package tui

import (
	"context"
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

// startupStub serves one endpoint with one fresh session.
func startupStub() *interactiveStub {
	return &interactiveStub{
		endpoints: []protocol.Endpoint{{EndpointID: "endpoint-1", Hostname: "ai-dev"}},
		reports:   map[string]protocol.InventoryReport{"endpoint-1": startupInventory()},
	}
}

func startupInventory() protocol.InventoryReport {
	report := testInventory()
	report.Sessions[0].SessionID = "res_session-1"
	report.Sessions[0].ProviderSessionID = "provider-session-1"
	return report
}

// runStartup executes one interactive scenario and returns both streams.
func runStartup(t *testing.T, stub InteractiveAPI, input string, options InteractiveOptions) (string, string) {
	t.Helper()
	var output, diagnostics strings.Builder
	if err := RunInteractive(context.Background(), stub, strings.NewReader(input), &output, &diagnostics, options); err != nil {
		t.Fatalf("RunInteractive: %v", err)
	}
	return output.String(), diagnostics.String()
}

func TestStartupRendersInventoryBeforeFirstPrompt(t *testing.T) {
	output, _ := runStartup(t, startupStub(), "quit\n", InteractiveOptions{})
	for _, header := range tableHeaders {
		if !strings.Contains(output, header) {
			t.Fatalf("startup inventory missing header %q: %q", header, output)
		}
	}
	if !strings.Contains(output, "provider-session-1") {
		t.Fatalf("startup inventory missing session row: %q", output)
	}
	headerIndex := strings.Index(output, "LAST_SUCCESS")
	promptIndex := strings.Index(output, "cluster> ")
	if headerIndex < 0 || promptIndex < 0 {
		t.Fatalf("startup output incomplete: %q", output)
	}
	if headerIndex > promptIndex {
		t.Fatalf("inventory rendered after the first prompt: %q", output)
	}
}

func TestStartupRowsBindSessionThroughCD(t *testing.T) {
	output, diagnostics := runStartup(t, startupStub(), "cd 1\nshow\nquit\n", InteractiveOptions{})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if !strings.Contains(output, "cluster[ai-dev/provider-session-1]") {
		t.Fatalf("startup row navigation did not enter session: %q", output)
	}
	if !strings.Contains(output, "session: res_session-1") {
		t.Fatalf("startup row navigation selected the wrong session: %q", output)
	}
}

func TestStartupLeavesWorkspaceScope(t *testing.T) {
	output, _ := runStartup(t, startupStub(), "quit\n", InteractiveOptions{})
	if !strings.Contains(output, "cluster> ") {
		t.Fatalf("workspace prompt missing: %q", output)
	}
	if strings.Contains(output, "cluster[") {
		t.Fatalf("startup entered a nested scope: %q", output)
	}
}

func TestStartupFailureKeepsReplAlive(t *testing.T) {
	stub := startupStub()
	stub.failList = true
	output, diagnostics := runStartup(t, stub, "help\nquit\n", InteractiveOptions{})
	if !strings.Contains(diagnostics, "error: temporary list failure") {
		t.Fatalf("startup failure not reported: %q", diagnostics)
	}
	if !strings.Contains(output, "Commands by scope:") {
		t.Fatalf("repl did not accept a command after startup failure: %q", output)
	}
}

func TestStartupFailureWritesErrorToStderr(t *testing.T) {
	stub := startupStub()
	stub.failList = true
	output, diagnostics := runStartup(t, stub, "quit\n", InteractiveOptions{})
	if !strings.Contains(diagnostics, "error: temporary list failure") {
		t.Fatalf("stderr missing startup error: %q", diagnostics)
	}
	if strings.Contains(output, "temporary list failure") {
		t.Fatalf("startup error leaked to stdout: %q", output)
	}
}

func TestStartupFailureHintsRefresh(t *testing.T) {
	stub := startupStub()
	stub.failList = true
	_, diagnostics := runStartup(t, stub, "quit\n", InteractiveOptions{})
	if !strings.Contains(diagnostics, `hint: run "refresh" to retry the inventory`) {
		t.Fatalf("stderr missing refresh hint: %q", diagnostics)
	}
}

func TestStartupFailureKeepsWorkspaceScope(t *testing.T) {
	stub := startupStub()
	stub.failList = true
	output, _ := runStartup(t, stub, "quit\n", InteractiveOptions{})
	if !strings.Contains(output, "cluster> ") {
		t.Fatalf("workspace prompt missing after failure: %q", output)
	}
	if strings.Contains(output, "cluster[") {
		t.Fatalf("failed startup changed scope: %q", output)
	}
}

func TestStartupInventoryHonorsColorPolicy(t *testing.T) {
	output, _ := runStartup(t, startupStub(), "quit\n", InteractiveOptions{Color: ColorPolicy{Enabled: false}})
	if strings.Contains(output, "\x1b") {
		t.Fatalf("startup inventory emitted ANSI with colors disabled: %q", output)
	}
	colored, _ := runStartup(t, startupStub(), "quit\n", InteractiveOptions{Color: ColorPolicy{Enabled: true}})
	if !strings.Contains(colored, ansiBoldCyan+"NO") {
		t.Fatalf("startup inventory missing bold cyan header: %q", colored)
	}
	if !strings.Contains(colored, ansiGreen+"running") {
		t.Fatalf("startup inventory missing green running state: %q", colored)
	}
}

func TestStartupInventoryKeepsCleanDefault(t *testing.T) {
	stub := startupStub()
	stub.reports = map[string]protocol.InventoryReport{}
	output, diagnostics := runStartup(t, stub, "quit\n", InteractiveOptions{})
	if !strings.Contains(output, "ai-dev") {
		t.Fatalf("startup inventory omitted a failed endpoint: %q", output)
	}
	if !strings.Contains(diagnostics, "endpoint-1") {
		t.Fatalf("startup inventory omitted the failure diagnostic: %q", diagnostics)
	}
}

func TestNonInteractiveListDoesNotRunStartupInventory(t *testing.T) {
	stub := startupStub()
	var output strings.Builder
	if err := (CommandRunner{API: stub}).List(context.Background(), &output, "", false); err != nil {
		t.Fatalf("List: %v", err)
	}
	if got := strings.Count(output.String(), "LAST_SUCCESS"); got != 1 {
		t.Fatalf("non-interactive list rendered %d tables, want 1: %q", got, output.String())
	}
	if stub.inventoryCalls != 1 {
		t.Fatalf("non-interactive list fetched %d inventories, want 1", stub.inventoryCalls)
	}
}
