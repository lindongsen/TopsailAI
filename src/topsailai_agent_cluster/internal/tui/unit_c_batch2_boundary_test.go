package tui

import (
	"context"
	"errors"
	"fmt"
	"io"
	"reflect"
	"strings"
	"testing"
)

// TestUnitCBatch2DispatcherQueues tests the real dispatcher, not a public reader queue.
func TestUnitCBatch2DispatcherQueues(t *testing.T) {
	for field := startFieldEndpoint; field <= startFieldRevision; field++ {
		for _, mode := range []string{"fatal", "eof"} {
			for _, order := range []string{"positional", "required-flags-order"} {
				t.Run(startFieldName(field)+"/"+mode+"/"+order, func(t *testing.T) {
					sentinel := errors.New("C19 dispatcher fatal")
					cause := error(io.EOF)
					if mode == "fatal" {
						cause = sentinel
					}
					lines := make(chan lineReadResult, 8)
					answers := []string{"endpoint-1", "resource-1", "profile-1"}
					for i := startFieldEndpoint; i < field; i++ {
						lines <- lineReadResult{line: answers[i]}
					}
					lines <- lineReadResult{err: cause}
					tails := []string{strings.TrimSuffix(unitC19Grammar(order), "\n"), "UNITC_QUEUE_SENTINEL", "quit"}
					for _, line := range tails {
						lines <- lineReadResult{line: line}
					}
					api := newUnitCAPI()
					state := interactiveState{}
					var out, diagnostics strings.Builder
					exit, err := executeInteractiveLine(context.Background(), api, &state, "start", lines, &out, &out, &diagnostics, InteractiveOptions{})
					var termination *startPromptTermination
					kind := startPromptEOF
					if mode == "fatal" {
						kind = startPromptFatal
					}
					if exit || !errors.As(err, &termination) || termination.kind != kind || !errors.Is(err, cause) {
						t.Fatalf("C19 error identity: exit=%t err=%v", exit, err)
					}
					// B2_QUEUE_RETURN: actual private FIFO consumption action seam.
					if len(lines) != 3 {
						t.Fatalf("C19 queue remainder: len=%d want=3", len(lines))
					}
					for _, want := range tails {
						if got := <-lines; got.line != want || got.err != nil {
							t.Fatalf("C19 queue remainder: got=%+v want=%q", got, want)
						}
					}
					expected := ""
					for i := startFieldEndpoint; i <= field; i++ {
						expected += unitCFieldToken(i)
					}
					if out.String() != expected || diagnostics.String() != "" {
						t.Fatalf("C19 terminal dispatch: output=%q diagnostics=%q", out.String(), diagnostics.String())
					}
					assertNoAPIActivity(t, api)
				})
			}
		}
	}
}

// TestUnitCBatch2ErrorIdentity checks exact public error objects and real wrapping.
func TestUnitCBatch2ErrorIdentity(t *testing.T) {
	for field := startFieldEndpoint; field <= startFieldRevision; field++ {
		for _, mode := range []string{"reader-raw", "reader-wrapped", "writer-raw", "writer-wrapped", "parent", "deadline", "eof"} {
			t.Run(startFieldName(field)+"/"+mode, func(t *testing.T) {
				d := newUnitCBatch2Driver(t, mode, true)
				d.startup(t, field)
				raw := errors.New("C19 identity raw")
				unrelated := errors.New("C19 unrelated")
				want := error(raw)
				if strings.HasSuffix(mode, "wrapped") {
					want = fmt.Errorf("C19 wrapped: %w", raw)
				}
				switch {
				case strings.HasPrefix(mode, "writer"):
					attempt := d.holdWizardHelp(t)
					d.outGate.reply(attempt, want)
				case mode == "parent":
					d.cancel()
					want = d.parent.Err()
				case mode == "deadline":
					d.gate.Arm()
					want = d.parent.Err()
				case mode == "eof":
					d.reply(t, *d.pending, "", io.EOF)
					want = nil
				default:
					d.reply(t, *d.pending, "", want)
				}
				d.ledger.release()
				got := d.waitRun(t)
				// B2_ERROR_RESULT: detached error identity sensitivity seam.
				if got != want || errors.Is(got, unrelated) || (want != nil && !errors.Is(got, want)) {
					t.Fatalf("C19 error identity: got=%v want exact=%v", got, want)
				}
				if strings.Contains(mode, "wrapped") && !errors.Is(got, raw) {
					t.Fatal("C19 error identity: lost wrapped cause")
				}
				d.assertTerminal(t, d.ready, "", 1)
			})
		}
	}
}

// TestUnitCBatch2TakenAnswerDiscarded models cancellation after selection, not kernel timing.
func TestUnitCBatch2TakenAnswerDiscarded(t *testing.T) {
	for field := startFieldEndpoint; field <= startFieldRevision; field++ {
		t.Run(startFieldName(field), func(t *testing.T) {
			ctx := &unitCObservedFatalContext{done: make(chan struct{}), errs: []error{nil, context.Canceled}}
			lines := make(chan lineReadResult, 1)
			lines <- lineReadResult{line: "stale-answer"}
			draft := startDraft{request: interactiveStartRequest{EndpointID: "e", ResourceID: "r", Profile: "p", ProfileRevision: "v"}}
			draft.missing[field] = true
			var out, diagnostics strings.Builder
			outcome, request, err := runStartPrompt(ctx, interactiveState{}, draft, lines, &out, &diagnostics, ColorPolicy{})
			// B2_TAKEN_ANSWER: detached stale outcome sensitivity seam.
			if len(lines) != 0 || outcome != startPromptCancel || !reflect.DeepEqual(request, interactiveStartRequest{}) || err != context.Canceled {
				t.Fatalf("C19 discarded answer: remaining=%d outcome=%v request=%+v err=%v", len(lines), outcome, request, err)
			}
		})
	}
}

// TestUnitCBatch2QueueSetupValidation rejects malformed manifests without timeouts.
func TestUnitCBatch2QueueSetupValidation(t *testing.T) {
	valid := unitCBatch2QueueProof{field: startFieldEndpoint, first: "help\n", expected: "help\n", firstOrdinal: 3, returnedOrdinal: 3, nextOrdinal: 4, held: true, parentLive: true}
	if err := valid.validate(); err != nil {
		t.Fatal(err)
	}
	cases := []struct {
		name   string
		mutate func(*unitCBatch2QueueProof)
	}{
		{"missing", func(p *unitCBatch2QueueProof) { p.first = "" }},
		{"wrong", func(p *unitCBatch2QueueProof) { p.first = "sentinel\n" }},
		{"newline", func(p *unitCBatch2QueueProof) { p.first = "help"; p.expected = "help" }},
		{"released", func(p *unitCBatch2QueueProof) { p.held = false }},
		{"terminated", func(p *unitCBatch2QueueProof) { p.parentLive = false }},
		{"return", func(p *unitCBatch2QueueProof) { p.returnedOrdinal = 0 }},
		{"next", func(p *unitCBatch2QueueProof) { p.nextOrdinal = 0 }},
		{"gap", func(p *unitCBatch2QueueProof) { p.firstOrdinal++ }},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			p := valid
			tc.mutate(&p)
			if err := p.validate(); err == nil {
				t.Fatal("C19 queue setup invalid: malformed proof accepted")
			}
		})
	}
}

// TestUnitCBatch2ReaderQueueRemainder checks the real reader with a controlled consumer.
func TestUnitCBatch2ReaderQueueRemainder(t *testing.T) {
	for field := startFieldEndpoint; field <= startFieldRevision; field++ {
		for _, mode := range []string{"parent", "deadline"} {
			for _, order := range []string{"positional", "required-flags-order"} {
				t.Run(startFieldName(field)+"/"+mode+"/"+order, func(t *testing.T) {
					reader := newUnitCTicketReader()
					results, worker, stop := startInputReader(reader, 8192)
					t.Cleanup(func() { stop(); _ = reader.Close(); worker.Wait() })
					grammar := unitC19Grammar(order)
					ticket := <-reader.entered
					if err := unitCReply(ticket, grammar, nil); err != nil {
						t.Fatal(err)
					}
					next := <-reader.entered // Single producer sent grammar before this Read entry.
					if next.n != ticket.n+1 || len(results) != 1 {
						t.Fatal("C19 queue setup invalid: no occupied first result")
					}
					parent, cancel := context.WithCancel(context.Background())
					defer cancel()
					deadline := newUnitCBatch2Deadline()
					var ctx context.Context = parent
					if mode == "deadline" {
						ctx = deadline
						deadline.Arm()
					} else {
						cancel()
					}
					if ctx.Err() == nil {
						t.Fatal("C19 queue setup invalid: parent still live")
					}
					// B2_READER_QUEUE_DRAIN: actual private source FIFO action seam.
					if len(results) != 1 {
						t.Fatalf("C19 queue remainder: len=%d", len(results))
					}
					got := <-results
					if got.line != strings.TrimSuffix(grammar, "\n") || got.err != nil {
						t.Fatalf("C19 queue remainder: %+v", got)
					}
				})
			}
		}
	}
}
