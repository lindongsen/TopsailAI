package tui

import (
	"context"
	"fmt"
	"reflect"
	"strings"
	"testing"
)

// unitC3State seeds every authority field without invoking mutating navigation.
func unitC3State(scope ScopeKind, rows string) interactiveState {
	s := seedUnitCState()
	s.Scope.Kind = scope
	s.Invalidated = true
	s.InvalidReason = "retained reason"
	row := s.Rows[1]
	row.AdapterID, row.EndpointLabel, row.AdapterLabel = "adapter", "endpoint label", "adapter label"
	row.ProviderSessionID, row.DisplayName, row.State = "provider", "display", "ready"
	row.Stale, row.Unknown, row.CollectionStatus = true, true, "failed"
	s.Rows[1] = row
	row.No, row.SessionID = 2, "session-2"
	s.Rows[2] = row
	if rows == "nil" {
		s.Rows = nil
	}
	if rows == "empty" {
		s.Rows = map[int]SessionRow{}
	}
	return s
}

// TestUnitCBatch3CancelState compares the complete live authority at each boundary.
func TestUnitCBatch3CancelState(t *testing.T) {
	for field := startFieldEndpoint; field <= startFieldRevision; field++ {
		for _, scope := range []ScopeKind{ScopeWorkspace, ScopeEndpoint} {
			for _, answer := range []string{"", "cancel"} {
				for _, rows := range []string{"nil", "empty", "populated"} {
					t.Run(fmt.Sprintf("%s/%s/%q/%s", startFieldName(field), scope, answer, rows), func(t *testing.T) {
						api := newUnitCAPI()
						state := unitC3State(scope, rows)
						before := cloneUnitCState(state)
						lines := make(chan lineReadResult, 4)
						for _, v := range []string{"endpoint-1", "resource-1", "profile-1"}[:field] {
							lines <- lineReadResult{line: v}
						}
						lines <- lineReadResult{line: answer}
						var out, diag strings.Builder
						exit, err := executeInteractiveLine(context.Background(), api, &state, "start", lines, &out, &out, &diag, InteractiveOptions{})
						want := ""
						for i := startFieldEndpoint; i <= field; i++ {
							want += startFieldDescription(i) + "\nstart." + startFieldName(i) + "> "
						}
						want += "start cancelled\n"
						if exit || err != nil || !reflect.DeepEqual(state, before) || out.String() != want || diag.String() != "" {
							t.Fatalf("C6 state: exit=%v err=%v state=%+v before=%+v out=%q want=%q diag=%q", exit, err, state, before, out.String(), want, diag.String())
						}
						assertNoAPIActivity(t, api)
					})
				}
			}
		}
	}
}

// TestUnitCBatch3SessionRejection verifies scope authority before any prompt/read.
func TestUnitCBatch3SessionRejection(t *testing.T) {
	state := unitC3State(ScopeSession, "populated")
	before := cloneUnitCState(state)
	api := newUnitCAPI()
	var out strings.Builder
	exit, err := executeInteractiveLine(context.Background(), api, &state, "start", make(chan lineReadResult), &out, &out, &out, InteractiveOptions{})
	want := `command "start" is unavailable in session scope; available commands: list, cd, show, info, resume, stop, inject, interrupt, ctl, drive, logs, send, status, refresh, help, quit`
	if exit || err == nil || err.Error() != want || out.Len() != 0 || !reflect.DeepEqual(state, before) {
		t.Fatalf("C6 session: exit=%v err=%v output=%q", exit, err, out.String())
	}
	assertNoAPIActivity(t, api)
}

// TestUnitCBatch3CancelRepl selects the original actual row after wizard cancellation.
func TestUnitCBatch3CancelRepl(t *testing.T) {
	for field := startFieldEndpoint; field <= startFieldRevision; field++ {
		t.Run(startFieldName(field), func(t *testing.T) {
			d := newUnitCBatch2Driver(t, "cancel", false)
			d.startup(t, field)
			d.reply(t, *d.pending, "cancel\n", nil)
			awaitExactOutput(t, d.output, d.ready+"start cancelled\nworkspace> ")
			d.assertUnchanged(t)
			d.reply(t, d.next(t), "1\n", nil)
			d.reply(t, d.next(t), "show\n", nil)
			d.reply(t, d.next(t), "quit\n", nil)
			unitC19Finish(t, d)
			got := d.output.String()
			if !strings.Contains(got, "session[host-1/provider-session-1]> ") || !strings.Contains(got, "session: res_session-1") || d.errors.String() != "" {
				t.Fatalf("C6 REPL: output=%q diagnostics=%q", got, d.errors.String())
			}
			after, intents := d.api.snapshot()
			delta := unitCAPIAdd(d.baseline, after)
			if delta != (unitCAPICounts{List: 3, Inventory: 3, Capability: 1, ListCommands: 1, Output: 1}) || len(intents) != 0 {
				t.Fatalf("C6 followup calls (navigation/show only): %+v intents=%d", delta, len(intents))
			}
		})
	}
}
