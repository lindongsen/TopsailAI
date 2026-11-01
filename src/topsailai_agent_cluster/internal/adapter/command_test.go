package adapter

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"strconv"
	"strings"
	"syscall"
	"testing"
	"time"

	"topsailai_agent_cluster/internal/protocol"
)

func TestMain(m *testing.M) {
	if os.Getenv("AGENT_CLUSTER_COMMAND_HELPER") == "1" {
		if path := os.Getenv("AGENT_CLUSTER_COMMAND_HELPER_ARGV"); path != "" {
			_ = os.WriteFile(path, []byte(strings.Join(os.Args[1:], "\x00")), 0o600)
		}
		if path := os.Getenv("AGENT_CLUSTER_COMMAND_HELPER_PID"); path != "" {
			_ = os.WriteFile(path, []byte(strconv.Itoa(os.Getpid())), 0o600)
		}
		switch os.Getenv("AGENT_CLUSTER_COMMAND_HELPER_OUTPUT") {
		case "output":
			_, _ = os.Stdout.WriteString(`{"data":"bounded provider output","truncated":false}`)
		case "oversized":
			data, _ := json.Marshal(map[string]any{"data": strings.Repeat("x", 1<<20), "truncated": false})
			_, _ = os.Stdout.Write(data)
			time.Sleep(5 * time.Second)
			if path := os.Getenv("AGENT_CLUSTER_COMMAND_HELPER_DONE"); path != "" {
				_ = os.WriteFile(path, []byte("complete\n"), 0o600)
			}
		case "discover":
			_, _ = os.Stdout.WriteString(`{"sessions":[],"complete":true}`)
		default:
			_ = json.NewEncoder(os.Stdout).Encode(map[string]any{"command_id": "cmd-1", "outcome": "accepted", "effect_certainty": "acknowledged", "delivery_boundary": "submitted"})
		}
		return
	}
	os.Exit(m.Run())
}

type commandMapper struct{ mapping ResourceMapping }

func (m commandMapper) GetOrCreateResourceID(context.Context, string, string, int64) (ResourceMapping, error) {
	return m.mapping, nil
}
func (m commandMapper) LookupResourceID(context.Context, string) (ResourceMapping, error) {
	return m.mapping, nil
}

func commandAdapterForTest(t *testing.T, mapper ResourceMapper) Adapter {
	t.Helper()
	a, err := NewCommandAdapter(CommandConfig{AdapterID: "adapter-1", ProviderType: "fixture", Command: os.Args[0], Args: []string{"-test.run=^$"}, Timeout: 5 * time.Second, ResourceMapper: mapper})
	if err != nil {
		t.Fatal(err)
	}
	return a
}

func TestCommandAdapterPassesTargetAndPayload(t *testing.T) {
	t.Setenv("AGENT_CLUSTER_COMMAND_HELPER", "1")
	argvPath := t.TempDir() + "/argv"
	t.Setenv("AGENT_CLUSTER_COMMAND_HELPER_ARGV", argvPath)
	a := commandAdapterForTest(t, commandMapper{mapping: ResourceMapping{AdapterID: "adapter-1", ProviderKey: "native-1", ResourceID: "res-1"}})
	result, err := a.Execute(context.Background(), ExecuteRequest{Intent: protocol.ImmutableIntent{CommandID: "cmd-1", Operation: "message.send", Target: &protocol.CommandTarget{ResourceID: "res-1", Generation: "gen-1"}, Payload: []byte(`{"text":"hello"}`)}})
	if err != nil {
		t.Fatal(err)
	}
	if result.Receipt.CommandID != "cmd-1" || result.Receipt.EffectCertainty != protocol.EffectAcknowledged {
		t.Fatalf("receipt=%#v", result.Receipt)
	}
	argv, err := os.ReadFile(argvPath)
	if err != nil {
		t.Fatal(err)
	}
	args := string(argv)
	for _, want := range []string{"--target-resource-id\x00native-1", "--target-generation\x00gen-1", "--payload\x00{\"text\":\"hello\"}"} {
		if !strings.Contains(args, want) {
			t.Fatalf("argv=%q missing %q", args, want)
		}
	}
	if strings.Contains(args, "res-1") {
		t.Fatalf("opaque resource ID leaked into argv=%q", args)
	}
}

func TestReadOutputTranslatesOpaqueResourceID(t *testing.T) {
	t.Setenv("AGENT_CLUSTER_COMMAND_HELPER", "1")
	t.Setenv("AGENT_CLUSTER_COMMAND_HELPER_OUTPUT", "output")
	argvPath := t.TempDir() + "/argv"
	t.Setenv("AGENT_CLUSTER_COMMAND_HELPER_ARGV", argvPath)
	a := commandAdapterForTest(t, commandMapper{mapping: ResourceMapping{AdapterID: "adapter-1", ProviderKey: "native-output", ResourceID: "res-output"}})
	result, err := a.ReadOutput(context.Background(), OutputRequest{Target: protocol.CommandTarget{ResourceID: "res-output", Generation: "gen-1"}, Limit: 32})
	if err != nil {
		t.Fatal(err)
	}
	if len(result.Lines) != 1 || !strings.Contains(result.Lines[0], "bounded provider") {
		t.Fatalf("result=%#v", result)
	}
	argv, err := os.ReadFile(argvPath)
	if err != nil {
		t.Fatal(err)
	}
	args := string(argv)
	if !strings.Contains(args, "--read-output\x00native-output") || strings.Contains(args, "res-output") {
		t.Fatalf("argv=%q", args)
	}
}

func TestOutputIsBoundedDuringRead(t *testing.T) {
	t.Setenv("AGENT_CLUSTER_COMMAND_HELPER", "1")
	t.Setenv("AGENT_CLUSTER_COMMAND_HELPER_OUTPUT", "oversized")
	pidPath := t.TempDir() + "/pid"
	donePath := t.TempDir() + "/done"
	t.Setenv("AGENT_CLUSTER_COMMAND_HELPER_PID", pidPath)
	t.Setenv("AGENT_CLUSTER_COMMAND_HELPER_DONE", donePath)
	a := commandAdapterForTest(t, commandMapper{mapping: ResourceMapping{AdapterID: "adapter-1", ProviderKey: "native-output"}})
	started := time.Now()
	result, err := a.ReadOutput(context.Background(), OutputRequest{Target: protocol.CommandTarget{ResourceID: "res-output"}, Limit: 16})
	if !errors.Is(err, ErrOutputTooLarge) {
		t.Fatalf("error=%v, want ErrOutputTooLarge", err)
	}
	if len(strings.Join(result.Lines, "\n")) > 16 {
		t.Fatalf("returned output length=%d", len(strings.Join(result.Lines, "\n")))
	}
	if _, statErr := os.Stat(donePath); !os.IsNotExist(statErr) {
		t.Fatalf("helper completed output: stat=%v", statErr)
	}
	pidData, readErr := os.ReadFile(pidPath)
	if readErr != nil {
		t.Fatal(readErr)
	}
	pid, parseErr := strconv.Atoi(strings.TrimSpace(string(pidData)))
	if parseErr != nil {
		t.Fatal(parseErr)
	}
	deadline := time.Now().Add(2 * time.Second)
	for time.Now().Before(deadline) {
		if killErr := syscall.Kill(pid, 0); errors.Is(killErr, syscall.ESRCH) {
			break
		}
		time.Sleep(10 * time.Millisecond)
	}
	if killErr := syscall.Kill(pid, 0); !errors.Is(killErr, syscall.ESRCH) {
		t.Fatalf("helper pid %d still exists: %v", pid, killErr)
	}
	if elapsed := time.Since(started); elapsed > 2*time.Second {
		t.Fatalf("bounded read waited too long: %s", elapsed)
	}
}

func TestNewCommandAdapterRejectsInvalidConfiguration(t *testing.T) {
	for _, config := range []CommandConfig{{}, {AdapterID: "a"}, {AdapterID: "a", ProviderType: "p", Command: "c"}} {
		if _, err := NewCommandAdapter(config); err == nil {
			t.Fatal(fmt.Sprintf("configuration %#v unexpectedly accepted", config))
		}
	}
}

func TestCommandAdapterMetadataAndValidation(t *testing.T) {
	a := commandAdapterForTest(t, nil)
	descriptor, err := a.Describe(context.Background())
	if err != nil || descriptor.AdapterID != "adapter-1" || len(descriptor.Capabilities.Capabilities) != 3 {
		t.Fatalf("descriptor=%#v err=%v", descriptor, err)
	}
	if _, err := a.Inspect(context.Background(), InspectRequest{}); err == nil {
		t.Fatal("empty inspect target was accepted")
	}
	if _, err := a.QueryCommand(context.Background(), CommandQuery{}); err != ErrUnsupported {
		t.Fatalf("query error=%v", err)
	}
	if _, err := a.Watch(context.Background()); err != ErrUnsupported {
		t.Fatalf("watch error=%v", err)
	}
	if err := a.Close(); err != nil {
		t.Fatal(err)
	}
}

func TestCommandAdapterUsesConfiguredCapabilities(t *testing.T) {
	capabilities := protocol.CapabilityDescriptor{Revision: "rev-1", Capabilities: []protocol.Capability{{Name: "custom.operation", Version: "v2"}}}
	a, err := NewCommandAdapter(CommandConfig{AdapterID: "adapter-1", ProviderType: "fixture", Command: os.Args[0], Timeout: 5 * time.Second, Capabilities: &capabilities})
	if err != nil {
		t.Fatal(err)
	}
	descriptor, err := a.Describe(context.Background())
	if err != nil || descriptor.Capabilities.Revision != "rev-1" || len(descriptor.Capabilities.Capabilities) != 1 || descriptor.Capabilities.Capabilities[0].Name != "custom.operation" {
		t.Fatalf("descriptor=%#v err=%v", descriptor, err)
	}
}

func TestCommandAdapterDiscoverAndInspect(t *testing.T) {
	t.Setenv("AGENT_CLUSTER_COMMAND_HELPER", "1")
	t.Setenv("AGENT_CLUSTER_COMMAND_HELPER_OUTPUT", "discover")
	a, err := NewCommandAdapter(CommandConfig{AdapterID: "adapter-1", ProviderType: "fixture", Command: os.Args[0], Args: []string{"-test.run=^$"}, Timeout: 5 * time.Second})
	if err != nil {
		t.Fatal(err)
	}
	result, err := a.Discover(context.Background(), DiscoverRequest{})
	if err != nil || !result.Complete {
		t.Fatalf("discover=%#v err=%v", result, err)
	}
}

func TestCommandAdapterRejectsMapperOwnershipMismatch(t *testing.T) {
	a := commandAdapterForTest(t, commandMapper{mapping: ResourceMapping{AdapterID: "other", ProviderKey: "native"}})
	if _, err := a.Execute(context.Background(), ExecuteRequest{Intent: protocol.ImmutableIntent{CommandID: "c", Operation: "send", Target: &protocol.CommandTarget{ResourceID: "r", Generation: "g"}}}); err == nil {
		t.Fatal("execute accepted a resource owned by another adapter")
	}
	if _, err := a.ReadOutput(context.Background(), OutputRequest{Target: protocol.CommandTarget{ResourceID: "r", Generation: "g"}, Limit: 1}); err == nil {
		t.Fatal("output accepted a resource owned by another adapter")
	}
}
