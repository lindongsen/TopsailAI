package tui

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"strings"
	"testing"
	"topsailai_agent_cluster/internal/protocol"
)

type launchStub struct {
	*interactiveStub
	fail  bool
	calls int
}

// GetLaunchOptions supplies a live handler separate from inventory summaries.
func (s *launchStub) GetLaunchOptions(_ context.Context, endpoint, adapterID string) (protocol.LaunchOptions, error) {
	s.calls++
	result := protocol.LaunchOptions{Handlers: []protocol.LaunchHandler{{AdapterID: "a", Revision: "v"}}, Projects: []protocol.Project{{Name: "工程", Path: "/work/my app"}}}
	if adapterID != "" && s.fail {
		return protocol.LaunchOptions{}, errors.New("offline")
	}
	return result, nil
}

// TestProjectLaunchWizard verifies selected/manual paths, fallback and cancellation.
func TestProjectLaunchWizard(t *testing.T) {
	for _, item := range []struct {
		name, input, folder string
		fail                bool
		admits              int
	}{
		{"select", "1\n--检查 literal $(no)\n", "/work/my app", false, 1},
		{"manual", "/work/other folder\ndo work\n", "/work/other folder", false, 1},
		{"fallback", "/work/manual\ndo work\n", "/work/manual", true, 1},
		{"cancel-folder", "cancel\n", "", false, 0},
		{"cancel-task", "1\ncancel\n", "", false, 0},
	} {
		t.Run(item.name, func(t *testing.T) {
			stub := &launchStub{interactiveStub: startupStub(), fail: item.fail}
			lines, done, stop := startInputReader(strings.NewReader(item.input), 8192)
			defer func() { stop(); done.Wait() }()
			var out strings.Builder
			err := projectLaunch(context.Background(), stub, stub, &interactiveState{}, "endpoint-1", lines, &out, &out, InteractiveOptions{})
			if err != nil {
				t.Fatal(err)
			}
			if stub.admit != item.admits || stub.calls != 2 {
				t.Fatalf("admit=%d calls=%d", stub.admit, stub.calls)
			}
			if item.admits == 1 {
				intent := stub.intents[0]
				if intent.Folder != item.folder || intent.LaunchProfileID != "a" || intent.ProfileRevision != "v" || intent.Target != nil {
					t.Fatalf("%#v", intent)
				}
				var payload map[string]string
				if err := json.Unmarshal(intent.Payload, &payload); err != nil || payload["task"] == "" {
					t.Fatal("task missing")
				}
				if item.name == "select" && payload["task"] != "--检查 literal $(no)" {
					t.Fatal(payload)
				}
			}
		})
	}
}

// TestLaunchAnswerFailure verifies EOF/overflow never become a truncated task.
func TestLaunchAnswerFailure(t *testing.T) {
	for _, input := range []string{"", strings.Repeat("x", 20) + "\n"} {
		lines, done, stop := startInputReader(strings.NewReader(input), 8)
		_, _, err := launchAnswer(context.Background(), lines, io.Discard, &interactiveState{}, "task")
		stop()
		done.Wait()
		if err == nil {
			t.Fatal("invalid input accepted")
		}
	}
}

type launchQueryFunc func(context.Context, string, string) (protocol.LaunchOptions, error)

// GetLaunchOptions adapts query scenarios without global state.
func (f launchQueryFunc) GetLaunchOptions(ctx context.Context, e, a string) (protocol.LaunchOptions, error) {
	return f(ctx, e, a)
}

// TestProjectLaunchErrors covers catalog, selection and task validation boundaries.
func TestProjectLaunchErrors(t *testing.T) {
	for _, item := range []struct {
		name, input string
		handlers    []protocol.LaunchHandler
		code        string
		queryFail   bool
	}{
		{name: "query-failure", queryFail: true},
		{name: "catalog-error", code: "unsupported"},
		{name: "empty"},
		{name: "multiple", input: "2\n1\nwork\n", handlers: []protocol.LaunchHandler{{AdapterID: "a", Revision: "v"}, {AdapterID: "b", Revision: "v"}}},
		{name: "bad-adapter", input: "9\n", handlers: []protocol.LaunchHandler{{AdapterID: "a"}, {AdapterID: "b"}}},
		{name: "bad-project", input: "999\n", handlers: []protocol.LaunchHandler{{AdapterID: "a", Revision: "v"}}},
		{name: "bad-folder", input: " bad \n", handlers: []protocol.LaunchHandler{{AdapterID: "a", Revision: "v"}}},
		{name: "nul-task", input: "1\nbad\x00task\n", handlers: []protocol.LaunchHandler{{AdapterID: "a", Revision: "v"}}},
	} {
		t.Run(item.name, func(t *testing.T) {
			stub := startupStub()
			query := launchQueryFunc(func(_ context.Context, e, a string) (protocol.LaunchOptions, error) {
				if item.queryFail {
					return protocol.LaunchOptions{}, errors.New("offline")
				}
				handlers := item.handlers
				if a != "" {
					handlers = []protocol.LaunchHandler{{AdapterID: a, Revision: "v"}}
				}
				return protocol.LaunchOptions{Handlers: handlers, ErrorCode: item.code, Projects: []protocol.Project{{Path: "/work/one"}}}, nil
			})
			lines, done, stop := startInputReader(strings.NewReader(item.input), 8192)
			err := projectLaunch(context.Background(), stub, query, &interactiveState{}, "endpoint-1", lines, io.Discard, io.Discard, InteractiveOptions{})
			stop()
			done.Wait()
			if item.name == "multiple" {
				if err != nil || stub.admit != 1 {
					t.Fatalf("%v %d", err, stub.admit)
				}
			} else if err == nil || stub.admit != 0 {
				t.Fatalf("%v %d", err, stub.admit)
			}
		})
	}
}

// TestProjectLaunchDispatch verifies production dispatch and fatal output handling.
func TestProjectLaunchDispatch(t *testing.T) {
	for _, fail := range []bool{false, true} {
		stub := &launchStub{interactiveStub: startupStub()}
		lines, done, stop := startInputReader(strings.NewReader("1\ninspect tests\n"), 8192)
		var output strings.Builder
		var out io.Writer = &output
		sentinel := errors.New("terminal unavailable")
		if fail {
			out = launchFailWriter{sentinel}
		}
		quit, err := executeInteractiveLine(context.Background(), stub, &interactiveState{}, "start endpoint-1", lines, out, out, io.Discard, InteractiveOptions{})
		stop()
		done.Wait()
		if quit {
			t.Fatal("unexpected quit")
		}
		if fail {
			if !errors.Is(unwrapStartTermination(err), sentinel) || stub.admit != 0 {
				t.Fatalf("%v admit=%d", err, stub.admit)
			}
		} else if err != nil || stub.admit != 1 {
			t.Fatalf("%v admit=%d", err, stub.admit)
		}
	}
}

type launchFailWriter struct{ err error }

// Write simulates a disconnected terminal without mutating shared output state.
func (w launchFailWriter) Write([]byte) (int, error) { return 0, w.err }

// TestProjectLaunchControlWords proves wizard control words never reach the launch query or admission.
func TestProjectLaunchControlWords(t *testing.T) {
	for _, item := range []struct {
		name, rest, input string
		wantErr           error
		wantAdmit         int
		wantCalls         int
		wantFolder        string
		wantHelp          bool
		wantUnavailable   bool
	}{
		{name: "help-endpoint", rest: "", input: "help start\nendpoint-1\n1\ndo work\n", wantAdmit: 1, wantCalls: 2, wantFolder: "/work/my app", wantHelp: true},
		{name: "help-folder", rest: "endpoint-1", input: "help\n1\ndo work\n", wantAdmit: 1, wantCalls: 2, wantFolder: "/work/my app", wantHelp: true},
		{name: "help-task", rest: "endpoint-1", input: "1\nhelp\ndo work\n", wantAdmit: 1, wantCalls: 2, wantFolder: "/work/my app", wantHelp: true},
		{name: "quit-endpoint", rest: "", input: "q\n", wantErr: errLaunchQuit},
		{name: "quit-task", rest: "endpoint-1", input: "1\nq\n", wantErr: errLaunchQuit, wantCalls: 2},
		{name: "refresh-folder", rest: "endpoint-1", input: "1\nr\n", wantErr: errLaunchRefresh, wantCalls: 2},
		{name: "quoted-control", rest: "endpoint-1", input: "'q'\ndo work\n", wantAdmit: 1, wantCalls: 2, wantFolder: "q"},
		{name: "unavailable-command", rest: "endpoint-1", input: "list\n1\ndo work\n", wantAdmit: 1, wantCalls: 2, wantFolder: "/work/my app", wantUnavailable: true},
	} {
		t.Run(item.name, func(t *testing.T) {
			stub := &launchStub{interactiveStub: startupStub()}
			lines, done, stop := startInputReader(strings.NewReader(item.input), 8192)
			defer func() { stop(); done.Wait() }()
			var out strings.Builder
			err := projectLaunch(context.Background(), stub, stub, &interactiveState{}, item.rest, lines, &out, &out, InteractiveOptions{})
			if item.wantErr != nil {
				if !errors.Is(err, item.wantErr) {
					t.Fatalf("err=%v want %v", err, item.wantErr)
				}
			} else if err != nil {
				t.Fatalf("err=%v", err)
			}
			if stub.admit != item.wantAdmit || stub.calls != item.wantCalls {
				t.Fatalf("admit=%d calls=%d want admit=%d calls=%d", stub.admit, stub.calls, item.wantAdmit, item.wantCalls)
			}
			if item.wantHelp && !strings.Contains(out.String(), "Syntax: start") {
				t.Fatalf("help missing: %q", out.String())
			}
			if item.wantUnavailable && !strings.Contains(out.String(), "command unavailable during start input") {
				t.Fatalf("diagnostic missing: %q", out.String())
			}
			if item.wantFolder != "" {
				if len(stub.intents) != 1 || stub.intents[0].Folder != item.wantFolder {
					t.Fatalf("intents=%#v", stub.intents)
				}
			}
		})
	}
}

// TestProjectLaunchQuitExitsRepl proves a wizard quit leaves interactive mode instead of printing an error.
func TestProjectLaunchQuitExitsRepl(t *testing.T) {
	stub := &launchStub{interactiveStub: startupStub()}
	lines, done, stop := startInputReader(strings.NewReader("q\n"), 8192)
	defer func() { stop(); done.Wait() }()
	var out strings.Builder
	quit, err := executeInteractiveLine(context.Background(), stub, &interactiveState{}, "start", lines, &out, &out, io.Discard, InteractiveOptions{})
	if !quit || err != nil {
		t.Fatalf("quit=%v err=%v", quit, err)
	}
	if stub.admit != 0 || stub.calls != 0 {
		t.Fatalf("admit=%d calls=%d", stub.admit, stub.calls)
	}
}
