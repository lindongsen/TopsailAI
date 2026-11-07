package tui

import (
	"errors"
	"fmt"
	"io"
	"strings"
	"testing"
)

// unitC19Grammar supplies the two existing complete parser grammars.
func unitC19Grammar(order string) string {
	flags := "--profile queued-profile --profile-revision queued-revision"
	if order == "required-flags-order" {
		flags = "--profile-revision queued-revision --profile queued-profile"
	}
	return "start queued-endpoint queued-resource " + flags + "\n"
}

// unitCBatch2QueueProof records only observed facts before termination.
type unitCBatch2QueueProof struct {
	field                                      startDraftField
	first, expected, second                    string
	firstOrdinal, returnedOrdinal, nextOrdinal int
	held, parentLive                           bool
}

// validate rejects incomplete or post-release occupancy claims.
func (p unitCBatch2QueueProof) validate() error {
	if p.first == "" || p.first != p.expected || !strings.HasSuffix(p.first, "\n") || !p.held || !p.parentLive || p.firstOrdinal != int(p.field)+3 || p.returnedOrdinal != p.firstOrdinal || p.nextOrdinal != p.firstOrdinal+1 {
		return fmt.Errorf("C19 queue setup invalid: %+v", p)
	}
	return nil
}

// unitC19Queue holds a real writer attempt and its causal reader proof.
type unitC19Queue struct {
	attempt unitCWriteAttempt
	proof   unitCBatch2QueueProof
	next    unitCReadTicket
}

// unitC19QueueBehind proves first occupancy while the only consumer is held.
func unitC19QueueBehind(t *testing.T, d *unitCBatch2Driver, field startDraftField, first, second string) unitC19Queue {
	t.Helper()
	attempt := d.holdWizardHelp(t)
	ticket := d.next(t)
	payload := first
	// B2_PREFETCH_FIRST_PAYLOAD: actual first queued bytes action seam.
	d.reply(t, ticket, payload, nil)
	event := d.readEvent(ticket.n)
	next := d.next(t) // The single worker must have sent first before entering this Read.
	attempts, _ := d.outGate.snapshot()
	held := len(attempts) == 1 && !attempts[0].Replied && attempts[0].Reply == attempt.Reply
	proof := unitCBatch2QueueProof{field: field, first: event.text, expected: first, second: second, firstOrdinal: ticket.n, returnedOrdinal: event.ordinal, nextOrdinal: next.n, held: held, parentLive: d.parent.Err() == nil}
	if second != "" {
		d.reply(t, next, second, nil)
		_ = d.readEvent(next.n)
	}
	// B2_SETUP_VALIDATION: detached actual occupancy manifest seam.
	if err := proof.validate(); err != nil {
		t.Fatal(err)
	}
	d.assertUnchanged(t)
	if d.output.String() != d.ready || d.errors.String() != "" {
		t.Fatal("C19 queue setup invalid: transcript changed")
	}
	t.Logf("confirmed first enqueue: %+v; second is delivery only", proof)
	return unitC19Queue{attempt: attempt, proof: proof, next: next}
}

// unitC19Release supplies a real held writer reply after a valid queue manifest.
func unitC19Release(t *testing.T, d *unitCBatch2Driver, q unitC19Queue, err error) {
	t.Helper()
	if got := q.proof.validate(); got != nil {
		t.Fatal(got)
	}
	// B2_QUEUE_BEFORE_RELEASE: actual writer result action seam.
	d.outGate.reply(q.attempt, err)
}

// TestUnitCBatch2QueuedTermination separates queued and physically unread tails.
func TestUnitCBatch2QueuedTermination(t *testing.T) {
	for field := startFieldEndpoint; field <= startFieldRevision; field++ {
		for _, mode := range []string{"fatal-reader", "fatal-output", "parent", "deadline", "eof"} {
			for _, order := range []string{"positional", "required-flags-order"} {
				t.Run(startFieldName(field)+"/"+mode+"/"+order, func(t *testing.T) {
					d := newUnitCBatch2Driver(t, mode, true)
					d.startup(t, field)
					grammar := unitC19Grammar(order)
					if _, err := parseInteractiveStart(strings.TrimSpace(strings.TrimPrefix(grammar, "start "))); err != nil {
						t.Fatal(err)
					}
					sentinel := errors.New("C19 terminal sentinel")
					var want error
					if mode == "fatal-reader" || mode == "eof" {
						terminal := error(io.EOF)
						if mode == "fatal-reader" {
							terminal = sentinel
							want = sentinel
						}
						d.reply(t, *d.pending, "", terminal)
					} else {
						q := unitC19QueueBehind(t, d, field, grammar, "UNITC_QUEUE_SENTINEL\n")
						var failure error
						switch mode {
						case "parent":
							d.cancel()
							want = d.parent.Err()
						case "deadline":
							d.gate.Arm()
							want = d.parent.Err()
						case "fatal-output":
							failure = sentinel
							want = sentinel
						}
						unitC19Release(t, d, q, failure)
					}
					d.ledger.release()
					got := d.waitRun(t)
					if got != want {
						t.Fatalf("C19 terminal dispatch: error=%v want=%v", got, want)
					}
					after, intents := d.api.snapshot()
					delta := unitCAPIAdd(d.baseline, after)
					output, diagnostics := d.output.String(), d.errors.String()
					terminalOutput := d.ready
					if mode == "parent" || mode == "deadline" {
						terminalOutput += unitCBatch2HelpText()
					}
					// B2_TERMINAL_RESULT: detached terminal observation sensitivity seam.
					if delta != (unitCAPICounts{}) || len(intents) != d.baselineIntents || output != terminalOutput || diagnostics != "" {
						t.Fatalf("C19 terminal dispatch: delta=%+v intents=%d output=%q diagnostics=%q", delta, len(intents), output, diagnostics)
					}
					if mode == "fatal-reader" || mode == "eof" {
						reads, _ := d.reader.Counts()
						tailReads := reads - d.pending.n
						// B2_TAIL_READ: physically unread tail observation sensitivity seam.
						if tailReads != 0 {
							t.Fatalf("C19 unread tail: reads=%d held-tail=%q", tailReads, grammar+"UNITC_QUEUE_SENTINEL\nquit\n")
						}
					}
				})
			}
		}
	}
}

// unitC19Finish cooperates with post-quit read cleanup without claiming no prefetch.
func unitC19Finish(t *testing.T, d *unitCBatch2Driver) {
	t.Helper()
	d.supplyEOF(t, d.next(t))
	d.ledger.release()
	if err := d.waitRun(t); err != nil {
		t.Fatalf("C19 continuation: runner=%v", err)
	}
}

// TestUnitCBatch2CancelAllowsQueuedStart proves exactly one later valid dispatch.
func TestUnitCBatch2CancelAllowsQueuedStart(t *testing.T) {
	for field := startFieldEndpoint; field <= startFieldRevision; field++ {
		for _, control := range []string{"cancel", "interrupt"} {
			for _, order := range []string{"positional", "required-flags-order"} {
				t.Run(startFieldName(field)+"/"+control+"/"+order, func(t *testing.T) {
					d := newUnitCBatch2Driver(t, control, false)
					d.startup(t, field)
					grammar := unitC19Grammar(order)
					if control == "interrupt" {
						q := unitC19QueueBehind(t, d, field, grammar, "quit\n")
						d.processedInterrupt()
						unitC19Release(t, d, q, nil)
					} else {
						d.reply(t, *d.pending, "cancel\n", nil)
						awaitExactOutput(t, d.output, d.ready+"start cancelled\nworkspace> ")
						d.reply(t, d.next(t), grammar, nil)
						d.reply(t, d.next(t), "quit\n", nil)
					}
					unitC19Finish(t, d)
					after, intents := d.api.snapshot()
					delta := unitCAPIAdd(d.baseline, after)
					// B2_CONTINUE_RESULT: detached continuation observation sensitivity seam.
					if delta != (unitCAPICounts{Capability: 1, Command: 1, Admit: 1}) || len(intents) != 1 || intents[0].EndpointID != "queued-endpoint" || intents[0].LaunchProfileID != "queued-profile" || intents[0].ProfileRevision != "queued-revision" {
						t.Fatalf("C19 continuation: delta=%+v intents=%+v", delta, intents)
					}
					expectedErrors := ""
					prefix := d.ready + "start cancelled\nworkspace> "
					if control == "interrupt" {
						expectedErrors = "interrupted\n"
						prefix = d.ready + unitCBatch2HelpText() + "workspace> "
					}
					suffix := "command submitted: unit-c-command; use status unit-c-command to query\nCommandID: unit-c-command\nStatus: finished\nDeliveryBoundary: \nEffectCertainty: \nErrorCode: \nworkspace> "
					if d.output.String() != prefix+suffix || d.errors.String() != expectedErrors {
						t.Fatalf("C19 continuation: output=%q errors=%q", d.output.String(), d.errors.String())
					}
				})
			}
		}
	}
}

// TestUnitCBatch2PrefetchedHelpQuit delivers both main controls before the signal.
func TestUnitCBatch2PrefetchedHelpQuit(t *testing.T) {
	for field := startFieldEndpoint; field <= startFieldRevision; field++ {
		t.Run(startFieldName(field), func(t *testing.T) {
			d := newUnitCBatch2Driver(t, "interrupt", false)
			d.startup(t, field)
			q := unitC19QueueBehind(t, d, field, "help\n", "quit\n")
			d.processedInterrupt()
			unitC19Release(t, d, q, nil)
			d.ledger.release()
			select {
			case ticket := <-d.reader.entered:
				d.supplyEOF(t, ticket)
			case <-d.run.done:
			}
			if err := d.waitRun(t); err != nil {
				t.Fatalf("C19 main help: runner=%v", err)
			}
			output := d.output.String()
			// B2_MAIN_HELP: detached main help observation sensitivity seam.
			want := d.ready + unitCBatch2HelpText() + "workspace> " + unitC19MainHelp() + "workspace> "
			if output != want || d.errors.String() != "interrupted\n" {
				t.Fatalf("C19 main help: output=%q want=%q errors=%q", output, want, d.errors.String())
			}
			d.assertUnchanged(t)
		})
	}
}

// unitC19MainHelp pins the workspace overview separately from wizard help.
func unitC19MainHelp() string {
	return "Current scope: workspace\n\nCommands:\n" +
		"  list [endpoint] [--clean]   list sessions across all endpoints\n  endpoints [endpoint-id]   list every registered endpoint with its connection state and freshness\n  cd [target]   navigate to an endpoint or session\n  show [endpoint-or-session]   show endpoint or session details\n  info [session]   show session detail by row number or session ID\n" + unitC19StartHelpLine() +
		"  stop [session]   stop a session by row number or session ID\n" +
		"  status [command-id]   show command result\n  refresh   refresh inventories\n  help [command]   show help\n  quit   exit\n\nNext: list -> <number> or cd <number> -> show/logs. Run help list for row selection rules.\nStart example: start <endpoint> <resource> --profile <id> --profile-revision <revision>\n" + commandPrefixHelp + "\nRun help all for every command and scope.\n"
}

// unitC19StartHelpLine is a fixed independent overview line shared by two scopes.
func unitC19StartHelpLine() string {
	return "  start <endpoint> <resource> [--profile <id>] [--profile-revision <revision>] [--folder <path>] [--task <text>]   start an agent through the selected endpoint; interactive mode executes directly and does not support --json\n"
}
