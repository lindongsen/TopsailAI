package tui

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"reflect"
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

// TestUnitCBatch3AllMasks runs every mathematical draft mask, not parser grammars.
func TestUnitCBatch3AllMasks(t *testing.T) {
	for mask := 0; mask < 16; mask++ {
		t.Run(fmt.Sprintf("mask-%04b", mask), func(t *testing.T) {
			draft := startDraft{request: interactiveStartRequest{EndpointID: "existing-e", ResourceID: "existing-r", Profile: "existing-p", ProfileRevision: "existing-v", Folder: "work", Payload: json.RawMessage(`{"tag":"existing"}`)}}
			want := draft.request
			lines := make(chan lineReadResult, 4)
			expected := ""
			for field := startFieldEndpoint; field <= startFieldRevision; field++ {
				if mask&(1<<field) == 0 {
					continue
				}
				draft.missing[field] = true
				value := fmt.Sprint(int(field) + 1)
				lines <- lineReadResult{line: value}
				switch field {
				case startFieldEndpoint:
					want.EndpointID = value
				case startFieldResource:
					want.ResourceID = value
				case startFieldProfile:
					want.Profile = value
				case startFieldRevision:
					want.ProfileRevision = value
				}
				expected += unitCFieldToken(field)
			}
			var out, diag strings.Builder
			outcome, got, err := runStartPrompt(context.Background(), interactiveState{}, draft, lines, &out, &out, &diag, ColorPolicy{})
			if err != nil || outcome != startPromptReady || !reflect.DeepEqual(got, want) || out.String() != expected || diag.Len() != 0 {
				t.Fatalf("F6 mask: outcome=%v request=%+v want=%+v err=%v out=%q wantout=%q diag=%q", outcome, got, want, err, out.String(), expected, diag.String())
			}
		})
	}
}

// TestUnitCBatch3QuotedControls proves quoted controls remain literal field values.
func TestUnitCBatch3QuotedControls(t *testing.T) {
	for _, answer := range []string{`"q"`, `'r'`, `'start'`, `"cancel"`} {
		t.Run(answer, func(t *testing.T) {
			draft := startDraft{request: interactiveStartRequest{EndpointID: "e", ResourceID: "r", Profile: "p"}}
			draft.missing[startFieldRevision] = true
			lines := make(chan lineReadResult, 1)
			lines <- lineReadResult{line: answer}
			outcome, got, err := runStartPrompt(context.Background(), interactiveState{}, draft, lines, io.Discard, io.Discard, io.Discard, ColorPolicy{})
			if err != nil || outcome != startPromptReady || got.ProfileRevision != answer[1:len(answer)-1] {
				t.Fatalf("F6 literal: outcome=%v got=%+v err=%v", outcome, got, err)
			}
		})
	}
}

// unitC3CheckIntent pins the complete externally meaningful start mapping.
func unitC3CheckIntent(t *testing.T, i protocol.ImmutableIntent, payload string, folder string) {
	t.Helper()
	if i.CommandID == "" || i.HashVersion != "v1" || i.OperationVersion != "v1" || i.PayloadSchemaVersion != "v1" || i.Operation != protocol.OperationAgentStart || i.EndpointID != "endpoint-1" || i.LaunchProfileID != "profile-1" || i.ProfileRevision != "revision-1" || i.CapabilityRevision != "cap-live-2" || i.Target != nil || string(i.Payload) != payload || i.Folder != folder {
		t.Fatalf("F6 exact intent: %+v", i)
	}
}

// TestUnitCBatch3LiveAuthority changes capability immediately before the real final answer.
func TestUnitCBatch3LiveAuthority(t *testing.T) {
	for _, mode := range []string{"success", "removed", "lookup", "admit", "command"} {
		t.Run(mode, func(t *testing.T) {
			d := newUnitCBatch2Driver(t, "cancel", false)
			d.api.mu.Lock()
			d.api.descriptor.Revision = "cap-old"
			d.api.mu.Unlock()
			d.startup(t, startFieldRevision)
			sentinel := errors.New("F6 " + mode)
			d.api.mu.Lock()
			switch mode {
			case "removed":
				d.api.descriptor.Capabilities = nil
			case "lookup":
				d.api.capErr = sentinel
			case "admit":
				d.api.admitErr = sentinel
			case "command":
				d.api.commandErr = sentinel
			}
			d.api.descriptor.Revision = "cap-live-2"
			d.api.mu.Unlock()
			d.reply(t, *d.pending, "revision-1\n", nil)
			d.reply(t, d.next(t), "exit\n", nil)
			unitC19Finish(t, d)
			after, intents := d.api.snapshot()
			delta := unitCAPIAdd(d.baseline, after)
			want := unitCAPICounts{List: 1, Capability: 1, Admit: 1, Command: 1}
			if mode == "removed" || mode == "lookup" {
				want.Admit = 0
				want.Command = 0
			}
			if mode == "admit" {
				want.Command = 0
			}
			if delta != want || len(intents) != want.Admit {
				t.Fatalf("F6 authority: delta=%+v want=%+v intents=%d", delta, want, len(intents))
			}
			if len(intents) == 1 {
				unitC3CheckIntent(t, intents[0], `{}`, "")
			}
			diag := d.errors.String()
			if mode == "success" {
				if diag != "" || strings.Count(d.output.String(), "command submitted:") != 1 {
					t.Fatalf("F6 completion: out=%q diag=%q", d.output.String(), diag)
				}
				return
			}
			if mode == "removed" {
				if !strings.Contains(diag, "support") {
					t.Fatalf("F6 removed: %q", diag)
				}
			} else if !strings.Contains(diag, sentinel.Error()) {
				t.Fatalf("F6 diagnostic: %q", diag)
			}
			if mode == "admit" {
				id := intents[0].CommandID
				if !strings.Contains(diag, "use status "+id) || !strings.Contains(diag, "result unknown") {
					t.Fatalf("F6 ambiguous submission: %q", diag)
				}
			}
			if mode == "command" && !strings.Contains(diag, "use status unit-c-command") {
				t.Fatalf("F6 query recovery: %q", diag)
			}
		})
	}
}

// TestUnitCBatch3DispatcherRequest pins grammar payload/folder and state except commandID.
func TestUnitCBatch3DispatcherRequest(t *testing.T) {
	api := newUnitCAPI()
	state := unitC3State(ScopeEndpoint, "populated")
	before := cloneUnitCState(state)
	var out strings.Builder
	lines := make(chan lineReadResult, 4)
	for _, v := range []string{"endpoint-1", "resource-1", "profile-1", "revision-1"} {
		lines <- lineReadResult{line: v}
	}
	exit, err := executeInteractiveLine(context.Background(), api, &state, `start --task "existing tag" --folder work`, lines, &out, &out, io.Discard, InteractiveOptions{})
	counts, intents := api.snapshot()
	if exit || err != nil || counts != (unitCAPICounts{List: 1, Capability: 1, Admit: 1, Command: 1}) || len(intents) != 1 {
		t.Fatalf("F6 dispatcher: exit=%v err=%v counts=%+v intents=%v", exit, err, counts, intents)
	}
	unitC3CheckIntent(t, intents[0], `{"task":"existing tag"}`, "work")
	before.commandID = "unit-c-command"
	if !reflect.DeepEqual(state, before) {
		t.Fatalf("F6 state: got=%+v want=%+v", state, before)
	}
}

// TestUnitCBatch3DispatcherErrors preserves actual sentinel identity without retries.
func TestUnitCBatch3DispatcherErrors(t *testing.T) {
	for _, mode := range []string{"lookup", "admit", "command"} {
		t.Run(mode, func(t *testing.T) {
			api := newUnitCAPI()
			sentinel := errors.New("F6 exact " + mode)
			switch mode {
			case "lookup":
				api.capErr = sentinel
			case "admit":
				api.admitErr = sentinel
			case "command":
				api.commandErr = sentinel
			}
			state := interactiveState{}
			_, err := executeInteractiveLine(context.Background(), api, &state, "start e r --profile p --profile-revision v", make(chan lineReadResult), io.Discard, io.Discard, io.Discard, InteractiveOptions{})
			if !errors.Is(err, sentinel) {
				t.Fatalf("F6 original error: %v", err)
			}
			c, _ := api.snapshot()
			want := unitCAPICounts{List: 1, Capability: 1, Admit: 1, Command: 1}
			if mode == "lookup" {
				want.Admit = 0
				want.Command = 0
			}
			if mode == "admit" {
				want.Command = 0
			}
			if c != want {
				t.Fatalf("F6 retries: %+v want=%+v", c, want)
			}
		})
	}
}

// TestUnitCBatch3DiagnosticsRefresh checks exact retries and refresh dispatch counts.
func TestUnitCBatch3DiagnosticsRefresh(t *testing.T) {
	for field := startFieldEndpoint; field <= startFieldRevision; field++ {
		for _, control := range []string{"invalid", "r", "refresh"} {
			t.Run(startFieldName(field)+"/"+control, func(t *testing.T) {
				api := newUnitCAPI()
				state := interactiveState{}
				lines := make(chan lineReadResult, 6)
				for _, v := range []string{"endpoint-1", "resource-1", "profile-1"}[:field] {
					lines <- lineReadResult{line: v}
				}
				if control == "invalid" {
					lines <- lineReadResult{line: "two tokens"}
					lines <- lineReadResult{line: "cancel"}
				} else {
					lines <- lineReadResult{line: control}
				}
				var out, diag strings.Builder
				exit, err := executeInteractiveLine(context.Background(), api, &state, "start", lines, &out, &out, &diag, InteractiveOptions{})
				if exit || err != nil {
					t.Fatalf("F6 control: exit=%v err=%v", exit, err)
				}
				prefix := ""
				for i := startFieldEndpoint; i <= field; i++ {
					prefix += unitCFieldToken(i)
				}
				if control == "invalid" {
					want := "error: start input requires one non-empty value\nusage: start <endpoint> <resource> [--profile <id>] [--profile-revision <revision>] [--folder <path>] [--task <text>]\nnext: Run help start for valid syntax.\n"
					if diag.String() != want || out.String() != prefix+unitCFieldToken(field)+"start cancelled\n" {
						t.Fatalf("F6 retry: out=%q diag=%q want=%q", out.String(), diag.String(), want)
					}
					assertNoAPIActivity(t, api)
				} else {
					counts, intents := api.snapshot()
					if counts != (unitCAPICounts{List: 1, Inventory: 1}) || len(intents) != 0 || diag.Len() != 0 || !strings.HasPrefix(out.String(), prefix+"start cancelled\n") || strings.Count(out.String(), "start cancelled\n") != 1 {
						t.Fatalf("F6 refresh: counts=%+v intents=%v out=%q diag=%q", counts, intents, out.String(), diag.String())
					}
				}
			})
		}
	}
}
