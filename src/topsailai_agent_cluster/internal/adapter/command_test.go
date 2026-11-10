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
			if err := os.WriteFile(path, []byte(strings.Join(os.Args[1:], "\x00")), 0o600); err != nil {
				fmt.Fprintf(os.Stderr, "write helper argv %q: %v\n", path, err)
				os.Exit(1)
			}
		}
		if path := os.Getenv("AGENT_CLUSTER_COMMAND_HELPER_PID"); path != "" {
			if err := os.WriteFile(path, []byte(strconv.Itoa(os.Getpid())), 0o600); err != nil {
				fmt.Fprintf(os.Stderr, "write helper pid %q: %v\n", path, err)
				os.Exit(1)
			}
		}
		switch os.Getenv("AGENT_CLUSTER_COMMAND_HELPER_OUTPUT") {
		case "output":
			if _, err := os.Stdout.WriteString(`{"data":"bounded provider output","truncated":false}`); err != nil {
				fmt.Fprintf(os.Stderr, "write helper output: %v\n", err)
				os.Exit(1)
			}
		case "oversized":
			data, err := json.Marshal(map[string]any{"data": strings.Repeat("x", 1<<20), "truncated": false})
			if err != nil {
				fmt.Fprintf(os.Stderr, "marshal helper output: %v\n", err)
				os.Exit(1)
			}
			var record *os.File
			if path := os.Getenv("AGENT_CLUSTER_COMMAND_HELPER_RECORD"); path != "" {
				record, err = os.OpenFile(path, os.O_CREATE|os.O_WRONLY|os.O_TRUNC, 0o600)
				if err != nil {
					fmt.Fprintf(os.Stderr, "open helper output record %q: %v\n", path, err)
					os.Exit(1)
				}
				defer record.Close()
			}
			for offset := 0; offset < len(data); {
				end := offset + 4096
				if end > len(data) {
					end = len(data)
				}
				written, writeErr := os.Stdout.Write(data[offset:end])
				if written > 0 && record != nil {
					if _, err := record.Write(data[offset : offset+written]); err != nil {
						fmt.Fprintf(os.Stderr, "write helper output record: %v\n", err)
						os.Exit(1)
					}
				}
				offset += written
				if writeErr != nil {
					fmt.Fprintf(os.Stderr, "write helper output: %v\n", writeErr)
					os.Exit(1)
				}
			}
			if path := os.Getenv("AGENT_CLUSTER_COMMAND_HELPER_DONE"); path != "" {
				if err := os.WriteFile(path, []byte("complete\n"), 0o600); err != nil {
					fmt.Fprintf(os.Stderr, "write helper completion marker %q: %v\n", path, err)
					os.Exit(1)
				}
			}
		case "discover":
			if _, err := os.Stdout.WriteString(`{"sessions":[],"complete":true}`); err != nil {
				fmt.Fprintf(os.Stderr, "write helper discovery output: %v\n", err)
				os.Exit(1)
			}
		case "discover-listed":
			// One listed session without a generation, which is the shape a
			// history row has: the record exists but no process is verified to
			// hold its output file.
			if _, err := os.Stdout.WriteString(`{"sessions":[{"session_id":"native-1","state":"idle"}],"complete":true}`); err != nil {
				fmt.Fprintf(os.Stderr, "write helper discovery output: %v\n", err)
				os.Exit(1)
			}
		case "execute-fail":
			// A failing provider reports its own diagnostic on stderr and exits
			// non-zero, which is the only evidence of why the call failed.
			fmt.Fprintln(os.Stderr, "helper provider diagnostic")
			os.Exit(2)
		case "execute-garbage":
			// A provider that answers with a non-JSON document is still the
			// provider's own answer, so it must survive as evidence.
			if _, err := os.Stdout.WriteString("not a json document"); err != nil {
				fmt.Fprintf(os.Stderr, "write helper garbage output: %v\n", err)
				os.Exit(1)
			}
		default:
			if err := json.NewEncoder(os.Stdout).Encode(map[string]any{"command_id": "cmd-1", "outcome": "accepted", "effect_certainty": "acknowledged", "delivery_boundary": "submitted"}); err != nil {
				fmt.Fprintf(os.Stderr, "write helper response: %v\n", err)
				os.Exit(1)
			}
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
	result, err := a.Execute(context.Background(), ExecuteRequest{Intent: protocol.ImmutableIntent{CommandID: "cmd-1", Operation: "message.send", Target: &protocol.CommandTarget{ResourceID: "res-1", ProviderGeneration: "gen-1"}, Payload: []byte(`{"text":"hello"}`)}})
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
	result, err := a.ReadOutput(context.Background(), OutputRequest{Target: protocol.CommandTarget{ResourceID: "res-output", ProviderGeneration: "gen-1"}, MaxBytes: 32})
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
	recordPath := t.TempDir() + "/output"
	t.Setenv("AGENT_CLUSTER_COMMAND_HELPER_PID", pidPath)
	t.Setenv("AGENT_CLUSTER_COMMAND_HELPER_DONE", donePath)
	t.Setenv("AGENT_CLUSTER_COMMAND_HELPER_RECORD", recordPath)
	a := commandAdapterForTest(t, commandMapper{mapping: ResourceMapping{AdapterID: "adapter-1", ProviderKey: "native-output"}})

	completedStarted := time.Now()
	if _, err := a.ReadOutput(context.Background(), OutputRequest{Target: protocol.CommandTarget{ResourceID: "res-output"}, MaxBytes: 2 << 20}); err != nil {
		t.Fatalf("complete output: %v", err)
	}
	if _, statErr := os.Stat(donePath); statErr != nil {
		t.Fatalf("completion marker was not written: %v", statErr)
	}
	if elapsed := time.Since(completedStarted); elapsed > 2*time.Second {
		t.Fatalf("completion marker was delayed: %s", elapsed)
	}
	if err := os.Remove(donePath); err != nil {
		t.Fatal(err)
	}

	started := time.Now()
	result, err := a.ReadOutput(context.Background(), OutputRequest{Target: protocol.CommandTarget{ResourceID: "res-output"}, MaxBytes: 16})
	if !errors.Is(err, ErrOutputTooLarge) {
		t.Fatalf("error=%v, want ErrOutputTooLarge", err)
	}
	if len(strings.Join(result.Lines, "\n")) > 16 {
		t.Fatalf("returned output length=%d", len(strings.Join(result.Lines, "\n")))
	}
	recorded, readErr := os.ReadFile(recordPath)
	if readErr != nil {
		t.Fatal(readErr)
	}
	fullOutputSize := len(`{"data":""}`) + (1 << 20) + len(`,"truncated":false}`)
	if len(recorded) == 0 || len(recorded) >= fullOutputSize {
		t.Fatalf("recorded output bytes=%d, want between 0 and full output size %d", len(recorded), fullOutputSize)
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
	if _, err := a.Execute(context.Background(), ExecuteRequest{Intent: protocol.ImmutableIntent{CommandID: "c", Operation: "send", Target: &protocol.CommandTarget{ResourceID: "r", ProviderGeneration: "g"}}}); err == nil {
		t.Fatal("execute accepted a resource owned by another adapter")
	}
	if _, err := a.ReadOutput(context.Background(), OutputRequest{Target: protocol.CommandTarget{ResourceID: "r", ProviderGeneration: "g"}, MaxBytes: 1}); err == nil {
		t.Fatal("output accepted a resource owned by another adapter")
	}
}
