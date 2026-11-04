package tui

import (
	"context"
	"errors"
	"fmt"
	"io"
	"os"
	"strings"
	"testing"
	"time"
)

// TestUnitCBatch2OwnedConvergence verifies actual field cancellation and owned cleanup.
func TestUnitCBatch2OwnedConvergence(t *testing.T) {
	for _, mode := range []string{"parent", "deadline"} {
		for field := startFieldEndpoint; field <= startFieldRevision; field++ {
			t.Run(mode+"-"+startFieldName(field), func(t *testing.T) {
				d := newUnitCBatch2Driver(t, mode, true)
				d.startup(t, field)
				if mode == "parent" {
					d.cancel()
				} else {
					d.gate.Arm()
				}
				waitClosed(t, d.ledger.entered, "watcher callback entry")
				d.ledger.release()
				got := d.waitRun(t)
				assertExactContext(t, got, d.parent.Err())
				d.assertTerminal(t, d.ready, "", 1)
				event := d.readEvent(d.pending.n)
				if event.n != 0 || event.err != io.ErrClosedPipe {
					t.Fatalf("C16 owned Read return: %+v", event)
				}
			})
		}
	}
}

// TestUnitCBatch2CommandInterrupt proves field cancellation without admission or premature Close.
func TestUnitCBatch2CommandInterrupt(t *testing.T) {
	for _, closeInput := range []bool{false, true} {
		for field := startFieldEndpoint; field <= startFieldRevision; field++ {
			t.Run(fmt.Sprintf("close-%t-%s", closeInput, startFieldName(field)), func(t *testing.T) {
				d := newUnitCBatch2Driver(t, "interrupt", closeInput)
				d.startup(t, field)
				attempt := d.holdWizardHelp(t)
				d.processedInterrupt()
				d.outGate.reply(attempt, nil)
				d.interruptContinuation(t)
				d.ledger.release()
				if got := d.waitRun(t); got != nil {
					t.Fatalf("C16 command interrupt: %v", got)
				}
				closes := 0
				if closeInput {
					closes = 1
				}
				d.assertTerminal(t, d.ready+unitCBatch2HelpText()+"cluster> ", "interrupted\n", closes)
			})
		}
	}
}

// TestUnitCBatch2WatcherBarrier preserves all twelve field/cause rows.
func TestUnitCBatch2WatcherBarrier(t *testing.T) {
	for _, mode := range []string{"parent", "deadline", "interrupt"} {
		for field := startFieldEndpoint; field <= startFieldRevision; field++ {
			t.Run(mode+"-"+startFieldName(field), func(t *testing.T) { runUnitCBatch2WatcherRow(t, mode, field, false) })
		}
	}
}

// observeHeldCallback joins either mutant arrival order before reporting failure.
func observeHeldCallback(t *testing.T, l *unitCBatch2WatcherLedger, probe bool) bool {
	t.Helper()
	if !probe {
		<-l.entered
		return false
	}
	select {
	case <-l.exitObserved:
	case <-l.entered:
		<-l.exitObserved
	}
	l.release()
	<-l.returned
	return true
}

// runUnitCBatch2WatcherRow holds callback ownership through all input cooperation.
func runUnitCBatch2WatcherRow(t *testing.T, mode string, field startDraftField, probe bool) {
	t.Helper()
	owned := mode != "interrupt"
	d := newUnitCBatch2Driver(t, mode, owned)
	d.startup(t, field)
	if mode == "interrupt" {
		attempt := d.holdWizardHelp(t)
		d.processedInterrupt()
		d.outGate.reply(attempt, nil)
		d.interruptContinuation(t)
	} else if mode == "parent" {
		d.cancel()
	} else {
		d.gate.Arm()
	}
	early := observeHeldCallback(t, d.ledger, probe)
	d.ledger.release()
	got := d.waitRun(t)
	if early {
		t.Fatal("C16 watcher barrier: exit observed while callback was held")
	}
	if owned {
		assertExactContext(t, got, d.parent.Err())
		d.assertTerminal(t, d.ready, "", 1)
		event := d.readEvent(d.pending.n)
		if event.n != 0 || event.err != io.ErrClosedPipe {
			t.Fatalf("C16 owned Read return: %+v", event)
		}
	} else {
		if got != nil {
			t.Fatalf("C16 watcher barrier: interrupt result=%v", got)
		}
		d.assertTerminal(t, d.ready+unitCBatch2HelpText()+"cluster> ", "interrupted\n", 0)
	}
	t.Logf("C16 watcher causal facts: %+v", d.ledger.snapshot())
}

// TestUnitCBatch2WatcherOmissionProbe activates only in the paired mutant overlay.
func TestUnitCBatch2WatcherOmissionProbe(t *testing.T) {
	const omissionProbe = false // B2_WATCHER_OMISSION_MODE
	if !omissionProbe {
		return
	}
	runUnitCBatch2WatcherRow(t, "parent", startFieldEndpoint, true)
}

// TestUnitCBatch2InitialStartupTermination distinguishes pre-worker and live API entry.
func TestUnitCBatch2InitialStartupTermination(t *testing.T) {
	for _, mode := range []string{"cancel", "deadline"} {
		for _, phase := range []string{"initial", "startup"} {
			t.Run(mode+"-"+phase, func(t *testing.T) {
				parent, cancel := context.WithCancel(context.Background())
				defer cancel()
				gate := newUnitCBatch2Deadline()
				var ctx context.Context = parent
				terminate := cancel
				if mode == "deadline" {
					ctx = gate
					terminate = gate.Arm
				}
				api := newUnitCAPI()
				reader := newUnitCTicketReader()
				observer := &unitCBatch2ReadObserver{inner: reader, events: make(chan unitCBatch2ReadEvent, 32)}
				out := &unitCStageWriter{changed: make(chan struct{}, 1)}
				errOut := &unitCStageWriter{changed: make(chan struct{}, 1)}
				ledger := newUnitCBatch2WatcherLedger()
				run := &unitCBatch2Run{done: make(chan struct{})}
				options := InteractiveOptions{CloseInput: true, Interrupt: make(chan os.Signal, 1), watcherBeforeDone: ledger.beforeDone, watcherExit: ledger.afterWait}
				if phase == "initial" {
					terminate()
					got := RunInteractive(ctx, api, observer, out, errOut, options)
					assertExactContext(t, got, ctx.Err())
					reads, closes := reader.Counts()
					if reads != 0 || closes != 0 || ledger.snapshot() != (unitCBatch2WatcherFacts{}) || out.String() != "" || errOut.String() != "" {
						t.Fatal("C16 initial: workers or output constructed")
					}
					assertNoAPIActivity(t, api)
					return
				}
				startup := &unitCBatch2StartupAPI{unitCAPI: api, entered: make(chan struct{})}
				t.Cleanup(func() { terminate(); ledger.release(); _ = reader.Close(); waitClosed(t, run.done, "startup cleanup") })
				go func() { run.err = RunInteractive(ctx, startup, observer, out, errOut, options); close(run.done) }()
				waitClosed(t, startup.entered, "startup ListEndpoints entry")
				// Read entry is independent of startup API entry; await it before cancellation.
				ticket := <-reader.entered
				terminate()
				waitClosed(t, ledger.entered, "startup watcher callback")
				ledger.release()
				waitClosed(t, run.done, "startup runner")
				assertExactContext(t, run.err, ctx.Err())
				ledger.assertReleasedOrder(t)
				event := <-observer.events
				if event.ordinal != ticket.n || event.n != 0 || event.err != io.ErrClosedPipe {
					t.Fatalf("C16 startup Read return: %+v", event)
				}
				counts, intents := api.snapshot()
				_, closes := reader.Counts()
				if counts != (unitCAPICounts{List: 1}) || len(intents) != 0 || closes != 1 || out.String() != "" || strings.Contains(errOut.String(), "cluster>") {
					t.Fatalf("C16 startup: counts=%+v closes=%d out=%q errors=%q", counts, closes, out.String(), errOut.String())
				}
			})
		}
	}
}

// drivePriorityInputs installs actual sources while the wizard help Write remains held.
func drivePriorityInputs(t *testing.T, d *unitCBatch2Driver, mode string, next unitCReadTicket, fatal error) error {
	t.Helper()
	switch mode {
	case "fatal-parent":
		d.cancel()
		t.Log("P observed: parent cancelled")
		return fatal
	case "fatal-interrupt":
		d.processedInterrupt()
		t.Log("I observed: callback entered")
		return fatal
	case "parent-eof":
		d.cancel()
		d.supplyEOF(t, next)
	case "parent-interrupt":
		d.processedInterrupt()
		d.cancel()
	case "interrupt-eof":
		d.processedInterrupt()
		d.supplyEOF(t, next)
	case "fatal-parent-interrupt-eof":
		d.processedInterrupt()
		d.supplyEOF(t, next)
		d.cancel()
		return fatal
	default:
		t.Fatalf("C16 priority: unknown mode %q", mode)
	}
	t.Logf("priority sources installed mode=%s parent=%v watcher=%+v", mode, d.parent.Err(), d.ledger.snapshot())
	return nil
}

// TestUnitCBatch2Priority verifies 24 genuine source competitions and four EOF controls.
func TestUnitCBatch2Priority(t *testing.T) {
	modes := []string{"fatal-parent", "fatal-interrupt", "parent-eof", "parent-interrupt", "interrupt-eof", "eof", "fatal-parent-interrupt-eof"}
	for field := startFieldEndpoint; field <= startFieldRevision; field++ {
		for _, mode := range modes {
			t.Run(startFieldName(field)+"-"+mode, func(t *testing.T) {
				d := newUnitCBatch2Driver(t, "parent", false)
				d.startup(t, field)
				raw := errors.New("C16 held help fatal")
				var fatal error = raw
				if mode == "fatal-interrupt" {
					fatal = fmt.Errorf("C16 wrapped: %w", raw)
				}
				var fault error
				wantOut, wantErrors := d.ready, ""
				if mode == "eof" {
					d.supplyEOF(t, *d.pending)
					d.pending = nil
				} else {
					attempt := d.holdWizardHelp(t)
					next := d.next(t)
					fault = drivePriorityInputs(t, d, mode, next, fatal)
					if !strings.Contains(mode, "eof") {
						d.supplyEOF(t, next)
					}
					d.outGate.reply(attempt, fault)
					if fault == nil {
						wantOut += unitCBatch2HelpText()
					}
					if mode == "interrupt-eof" {
						wantOut += "cluster> "
						wantErrors = "interrupted\n"
					}
				}
				d.ledger.release()
				got := d.waitRun(t)
				if fault != nil {
					// B2_FATAL_RESULT: detached priority result sensitivity seam.
					if got != fatal || !errors.Is(got, raw) || errors.Is(got, errors.New("unrelated")) {
						t.Fatalf("C16 fatal priority: got=%v want identical=%v", got, fatal)
					}
				} else if strings.HasPrefix(mode, "parent") {
					// B2_PARENT_EOF_RESULT: detached parent result sensitivity seam.
					assertExactContext(t, got, d.parent.Err())
				} else if got != nil {
					t.Fatalf("C16 EOF priority: got=%v want=nil", got)
				}
				// B2_INTERRUPT_ACK: detached acknowledgement sensitivity seam.
				d.assertTerminal(t, wantOut, wantErrors, 0)
				t.Logf("priority winner mode=%s result=%v", mode, got)
			})
		}
	}
}

// TestUnitCBatch2FinalAnswerCancellation cancels before bufio receives final revision bytes.
func TestUnitCBatch2FinalAnswerCancellation(t *testing.T) {
	for _, mode := range []string{"parent", "deadline"} {
		t.Run(mode+"-final-answer", func(t *testing.T) {
			d := newUnitCBatch2Configured(t, unitCBatch2Config{mode: mode, closeInput: true, finalOrdinal: 5})
			d.startup(t, startFieldRevision)
			if d.pending.n != 5 {
				t.Fatal("C16 final hook: wrong ordinal")
			}
			ticket := *d.pending
			d.pending = nil
			d.reply(t, ticket, "revision-1\n", nil)
			<-d.observer.finalHit
			if d.parent.Err() == nil {
				t.Fatal("C16 final hook: parent live")
			}
			event := d.readEvent(5)
			if event.ordinal != 5 || event.n != len("revision-1\n") || event.text != "revision-1\n" || event.err != nil {
				t.Fatalf("C16 final hook: %+v", event)
			}
			waitClosed(t, d.ledger.entered, "final callback")
			d.ledger.release()
			got := d.waitRun(t)
			assertExactContext(t, got, d.parent.Err())
			after, intents := d.api.snapshot()
			// B2_FINAL_DELIVER: detached-count sensitivity seam after real hook.
			if unitCAPIAdd(d.baseline, after) != (unitCAPICounts{}) || len(intents) != d.baselineIntents {
				t.Fatalf("C16 final cancellation admitted: before=%+v after=%+v delta=%+v intents=%d baselineIntents=%d parent=%v output=%q", d.baseline, after, unitCAPIAdd(d.baseline, after), len(intents), d.baselineIntents, d.parent.Err(), d.output.String())
			}
			d.assertTerminal(t, d.ready, "", 1)
			t.Logf("final Read receipt ordinal=%d n=%d text=%q parent=%v", event.ordinal, event.n, event.text, d.parent.Err())
		})
	}
}

// TestUnitCBatch2CompleteDraftCancelled checks the real dispatcher before admission.
func TestUnitCBatch2CompleteDraftCancelled(t *testing.T) {
	for _, mode := range []string{"complete-draft", "complete-draft-repeat"} {
		t.Run(mode, func(t *testing.T) {
			ctx, cancel := context.WithCancel(context.Background())
			defer cancel()
			if mode == "complete-draft" {
				cancel()
			} else {
				ctx, cancel = context.WithDeadline(context.Background(), time.Unix(1, 0))
				defer cancel()
			}
			api := newUnitCAPI()
			state := seedUnitCState()
			var out, errOut strings.Builder
			exit, err := executeInteractiveLine(ctx, api, &state, "start endpoint-1 resource-1 --profile profile-1 --profile-revision revision-1", make(chan lineReadResult), &out, &out, &errOut, InteractiveOptions{})
			assertExactContext(t, err, ctx.Err())
			assertNoAPIActivity(t, api)
			if exit || out.String() != "" || errOut.String() != "" {
				t.Fatalf("C16 complete draft: exit=%t out=%q errors=%q", exit, out.String(), errOut.String())
			}
		})
	}
}
