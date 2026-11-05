package topsailai

import (
	"context"
	"encoding/json"
	"strings"
	"testing"
	"topsailai_agent_cluster/internal/adapter"
	"topsailai_agent_cluster/internal/protocol"
)

// TestProjectsContract verifies one literal provider query and fail-closed decoding.
func TestProjectsContract(t *testing.T) {
	for _, item := range []struct {
		body  string
		valid bool
	}{
		{`[]`, true}, {`[{"name":"工程","path":"/work/my app"}]`, true},
		{`null`, false}, {`{}`, false}, {`[{"path":""}]`, false}, {`[{"path":"/bad\npath"}]`, false},
		{strings.Repeat(" ", protocol.MaxProjectBytes+1), false},
	} {
		runner := &fakeRunner{out: []byte(item.body)}
		a := newTestAdapter(t, runner)
		a.config.MaxOutput = protocol.MaxProjectBytes + 10
		_, err := a.Projects(context.Background())
		if (err == nil) != item.valid {
			t.Fatalf("valid=%v err=%v", item.valid, err)
		}
		if strings.Join(runner.args, " ") != "project list --json" {
			t.Fatal(runner.args)
		}
	}
}

// TestInitialTaskArgv ensures exact text and safe leading-dash handling.
func TestInitialTaskArgv(t *testing.T) {
	task := "--inspect 中文\n literal $(nothing)"
	payload, _ := json.Marshal(map[string]string{"task": task})
	runner := &fakeRunner{out: []byte(`{"delivery_state":"submitted"}`)}
	a := newTestAdapter(t, runner)
	_, err := a.Execute(context.Background(), adapter.ExecuteRequest{Intent: protocol.ImmutableIntent{Operation: "agent.start", LaunchProfileID: "a1", Folder: "/work/my app", Payload: payload}})
	args := runner.args
	if err != nil || args[len(args)-1] != "--task="+task {
		t.Fatalf("%v %v", args, err)
	}
	for _, bad := range []string{`null`, `[]`, `{"task":null}`, `{"task":4}`, `{"task":" "}`, `{"task":"\u0000"}`} {
		if _, err := a.Execute(context.Background(), adapter.ExecuteRequest{Intent: protocol.ImmutableIntent{Operation: "agent.start", LaunchProfileID: "a1", Payload: json.RawMessage(bad)}}); err == nil {
			t.Fatalf("accepted %s", bad)
		}
	}
	payload, _ = json.Marshal(map[string]string{"task": strings.Repeat("é", 4097)})
	if _, _, err := initialTask(payload); err == nil {
		t.Fatal("accepted byte overflow")
	}
	if _, supplied, err := initialTask([]byte(`{}`)); err != nil || supplied {
		t.Fatal("omission changed")
	}
}
