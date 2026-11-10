package tui

import (
	"context"
	"errors"
	"strings"
	"testing"
	"time"

	"topsailai_agent_cluster/internal/protocol"
)

// recoveryRequest is the intent the recovery tests follow. Its target is
// deliberately different from the fixture selection, so a snapshot that reads
// the current selection instead of the followed session is visible.
var recoveryRequest = followRequest{
	EndpointID:         "endpoint-followed",
	ResourceID:         "res-followed",
	ProviderGeneration: "generation-followed",
}

// newRecoverySession starts a session over an explicit record channel, so a test
// controls exactly which records arrive and when the stream ends.
func newRecoverySession(records chan protocol.OutputFollowRecord) *followSession {
	return newFollowSessionWithRecords(records, func() {}, ColorPolicy{}, recoveryRequest)
}

// waitPending blocks until the pump has queued provider bytes that the terminal
// has not received yet. That is the state a fast keypress leaves behind.
func waitPending(t *testing.T, session *followSession) {
	t.Helper()
	deadline := time.Now().Add(5 * time.Second)
	for {
		session.mu.Lock()
		pending := session.providerPending
		session.mu.Unlock()
		if pending > 0 {
			return
		}
		if time.Now().After(deadline) {
			t.Fatal("the pump never queued provider bytes")
		}
		time.Sleep(time.Millisecond)
	}
}

// TestFollowRecoveryTriggerTable pins every row of the agreed trigger table. The
// two independent triggers exist because they cover different failures: an
// abnormal end can break after printing part of the tail, and a keypress can
// discard bytes that were received but never printed.
func TestFollowRecoveryTriggerTable(t *testing.T) {
	for _, c := range []struct {
		name    string
		records []protocol.OutputFollowRecord
		// printBeforeStop hands the pending bytes to the terminal before the
		// keypress, which is what the editor's idle tick does.
		printBeforeStop bool
		stop            bool
		// operatorContinued reports that the keypress became a real command, so
		// the keypress trigger declines while an abnormal end still recovers.
		operatorContinued bool
		wantNeeded        bool
		wantCode          string
	}{
		{
			name:    "clean end with nothing to show does not recover",
			records: []protocol.OutputFollowRecord{{End: true}},
		},
		{
			name:    "clean end after printing does not recover",
			records: []protocol.OutputFollowRecord{{Lines: []string{"tail"}}, {End: true}},
		},
		{
			name:       "abnormal end after printing recovers",
			records:    []protocol.OutputFollowRecord{{Lines: []string{"tail"}}, {End: true, ErrorCode: "consumer_overflow"}},
			wantNeeded: true,
			wantCode:   "consumer_overflow",
		},
		{
			name:       "abnormal end before printing recovers",
			records:    []protocol.OutputFollowRecord{{End: true, ErrorCode: "provider_error"}},
			wantNeeded: true,
			wantCode:   "provider_error",
		},
		{
			name:    "endpoint offline does not recover",
			records: []protocol.OutputFollowRecord{{End: true, ErrorCode: "endpoint_offline"}},
		},
		{
			name:            "keypress after printing does not recover",
			records:         []protocol.OutputFollowRecord{{Lines: []string{"tail"}}},
			printBeforeStop: true,
			stop:            true,
		},
		{
			name:       "keypress before printing recovers",
			records:    []protocol.OutputFollowRecord{{Lines: []string{"tail"}}},
			stop:       true,
			wantNeeded: true,
			wantCode:   "no_output",
		},
		{
			name:              "keypress that became a command does not recover",
			records:           []protocol.OutputFollowRecord{{Lines: []string{"tail"}}},
			stop:              true,
			operatorContinued: true,
		},
		{
			name:              "abnormal end still recovers after a command",
			records:           []protocol.OutputFollowRecord{{End: true, ErrorCode: "consumer_overflow"}},
			operatorContinued: true,
			wantNeeded:        true,
			wantCode:          "consumer_overflow",
		},
	} {
		t.Run(c.name, func(t *testing.T) {
			records := make(chan protocol.OutputFollowRecord, len(c.records)+1)
			for _, record := range c.records {
				records <- record
			}
			// A stream that is stopped by a keypress must still be open, so the
			// stop is the operator's action rather than a reported end.
			if !c.stop {
				close(records)
			}
			session := newRecoverySession(records)
			defer session.Stop()
			if c.stop {
				waitPending(t, session)
				if c.printBeforeStop {
					if _, err := session.Idle(); err != nil {
						t.Fatalf("Idle: %v", err)
					}
				}
				session.Stop()
			} else {
				waitEnded(t, session)
				if _, err := session.Idle(); err != nil {
					t.Fatalf("Idle: %v", err)
				}
			}
			request, code, needed := session.Recovery(c.operatorContinued)
			if needed != c.wantNeeded {
				t.Fatalf("needed=%v, want %v (code=%q)", needed, c.wantNeeded, code)
			}
			if code != c.wantCode {
				t.Fatalf("code=%q, want %q", code, c.wantCode)
			}
			if !needed {
				if request != (followRequest{}) {
					t.Fatalf("a declined recovery returned a request: %+v", request)
				}
				return
			}
			if request != recoveryRequest {
				t.Fatalf("request=%+v, want the followed intent %+v", request, recoveryRequest)
			}
		})
	}
}

// TestFollowRecoveryInterruptedStreamRecovers proves a channel that closes
// without a terminal record is treated as an abnormal end, because the client
// reports that case as stream_interrupted rather than a clean finish.
func TestFollowRecoveryInterruptedStreamRecovers(t *testing.T) {
	records := make(chan protocol.OutputFollowRecord)
	close(records)
	session := newRecoverySession(records)
	defer session.Stop()
	waitEnded(t, session)
	_, code, needed := session.Recovery(false)
	if !needed || code != "stream_interrupted" {
		t.Fatalf("needed=%v code=%q, want a stream_interrupted recovery", needed, code)
	}
}

// TestFollowRecoveryDoesNotCountItsOwnStatusLine proves the printed evidence is
// provider output only. A stream that ends with nothing but its own status line
// showed the operator no output, so the status line must not satisfy the
// printed condition.
func TestFollowRecoveryDoesNotCountItsOwnStatusLine(t *testing.T) {
	records := make(chan protocol.OutputFollowRecord, 2)
	records <- protocol.OutputFollowRecord{End: true}
	close(records)
	session := newRecoverySession(records)
	defer session.Stop()
	waitEnded(t, session)
	payload, err := session.Idle()
	if err != nil {
		t.Fatalf("Idle: %v", err)
	}
	if !strings.Contains(string(payload), "follow ended") {
		t.Fatalf("the status line was not rendered: %q", payload)
	}
	session.mu.Lock()
	printed := session.providerPrinted
	session.mu.Unlock()
	if printed {
		t.Fatal("the status line was counted as provider output")
	}
}

// TestFollowRecoveryCountsProviderOutput proves the converse, so the previous
// test cannot pass because the counter never moves at all.
func TestFollowRecoveryCountsProviderOutput(t *testing.T) {
	records := make(chan protocol.OutputFollowRecord, 2)
	records <- protocol.OutputFollowRecord{Lines: []string{"tail"}}
	records <- protocol.OutputFollowRecord{End: true}
	close(records)
	session := newRecoverySession(records)
	defer session.Stop()
	waitEnded(t, session)
	if _, err := session.Idle(); err != nil {
		t.Fatalf("Idle: %v", err)
	}
	session.mu.Lock()
	printed := session.providerPrinted
	session.mu.Unlock()
	if !printed {
		t.Fatal("provider output was not counted as printed")
	}
}

// TestRecoverFollowOutputReadsTheFollowedTarget proves the recovery snapshot
// addresses the session that was followed, not whatever the selection happens to
// be when the stream ends.
func TestRecoverFollowOutputReadsTheFollowedTarget(t *testing.T) {
	records := make(chan protocol.OutputFollowRecord, 2)
	records <- protocol.OutputFollowRecord{End: true, ErrorCode: "consumer_overflow"}
	close(records)
	session := newRecoverySession(records)
	defer session.Stop()
	waitEnded(t, session)
	stub := &interactiveStub{}
	var out strings.Builder
	if err := recoverFollowOutput(context.Background(), stub, session, &out, InteractiveOptions{}, false); err != nil {
		t.Fatalf("recoverFollowOutput: %v", err)
	}
	if len(stub.outputRequests) != 1 {
		t.Fatalf("snapshot reads=%d, want one", len(stub.outputRequests))
	}
	got := stub.outputRequests[0]
	if got.endpointID != recoveryRequest.EndpointID || got.resourceID != recoveryRequest.ResourceID || got.generation != recoveryRequest.ProviderGeneration {
		t.Fatalf("snapshot target=%+v, want the followed intent %+v", got, recoveryRequest)
	}
	rendered := out.String()
	if !strings.Contains(rendered, "follow ended: consumer_overflow; showing one snapshot instead") {
		t.Fatalf("the recovery reason was not labelled: %q", rendered)
	}
	if !strings.Contains(rendered, "log") {
		t.Fatalf("the snapshot body was not rendered: %q", rendered)
	}
}

// TestRecoverFollowOutputLabelsAKeypressStop proves the keypress case names its
// own reason, so the operator is not told the stream ended when they stopped it.
func TestRecoverFollowOutputLabelsAKeypressStop(t *testing.T) {
	records := make(chan protocol.OutputFollowRecord, 1)
	records <- protocol.OutputFollowRecord{Lines: []string{"tail"}}
	session := newRecoverySession(records)
	defer session.Stop()
	waitPending(t, session)
	session.Stop()
	stub := &interactiveStub{}
	var out strings.Builder
	if err := recoverFollowOutput(context.Background(), stub, session, &out, InteractiveOptions{}, false); err != nil {
		t.Fatalf("recoverFollowOutput: %v", err)
	}
	if !strings.Contains(out.String(), "follow stopped before any output; showing one snapshot instead") {
		t.Fatalf("the keypress reason was not labelled: %q", out.String())
	}
}

// TestRecoverFollowOutputSkipsAHealthyStream proves a stream that showed output
// and ended cleanly reads nothing further, so the fallback never adds a second
// read to a normal follow.
func TestRecoverFollowOutputSkipsAHealthyStream(t *testing.T) {
	records := make(chan protocol.OutputFollowRecord, 2)
	records <- protocol.OutputFollowRecord{Lines: []string{"tail"}}
	records <- protocol.OutputFollowRecord{End: true}
	close(records)
	session := newRecoverySession(records)
	defer session.Stop()
	waitEnded(t, session)
	if _, err := session.Idle(); err != nil {
		t.Fatalf("Idle: %v", err)
	}
	stub := &interactiveStub{}
	var out strings.Builder
	if err := recoverFollowOutput(context.Background(), stub, session, &out, InteractiveOptions{}, false); err != nil {
		t.Fatalf("recoverFollowOutput: %v", err)
	}
	if len(stub.outputRequests) != 0 {
		t.Fatalf("a healthy stream triggered %d snapshot reads", len(stub.outputRequests))
	}
	if out.Len() != 0 {
		t.Fatalf("a healthy stream printed a recovery line: %q", out.String())
	}
}

// recoveryFailStub fails the snapshot read, so the recovery path can be proven to
// degrade into a diagnostic instead of a command failure.
type recoveryFailStub struct {
	interactiveStub
	err error
}

// GetOutput shadows the embedded stub so the snapshot read fails.
func (s *recoveryFailStub) GetOutput(context.Context, string, string, string, int, int) (protocol.OutputSnapshotResponse, error) {
	return protocol.OutputSnapshotResponse{}, s.err
}

// TestRecoverFollowOutputDegradesAFailedSnapshot proves a failed recovery read is
// a diagnostic, never an error: the stream already ended and the operator's
// command was accepted before it started.
func TestRecoverFollowOutputDegradesAFailedSnapshot(t *testing.T) {
	records := make(chan protocol.OutputFollowRecord, 2)
	records <- protocol.OutputFollowRecord{End: true, ErrorCode: "consumer_overflow"}
	close(records)
	session := newRecoverySession(records)
	defer session.Stop()
	waitEnded(t, session)
	stub := &recoveryFailStub{err: errors.New("endpoint unavailable")}
	var out strings.Builder
	if err := recoverFollowOutput(context.Background(), stub, session, &out, InteractiveOptions{}, false); err != nil {
		t.Fatalf("a failed recovery read became a command failure: %v", err)
	}
	rendered := out.String()
	if !strings.Contains(rendered, "follow recovery") {
		t.Fatalf("the failure was not attributed to the recovery: %q", rendered)
	}
	if !strings.Contains(rendered, "endpoint unavailable") {
		t.Fatalf("the failure detail was lost: %q", rendered)
	}
}

// TestRecoverFollowOutputIgnoresASessionWithoutTheSeam proves the auto-refresh
// loop keeps its current behaviour, because it cannot report a missing output.
func TestRecoverFollowOutputIgnoresASessionWithoutTheSeam(t *testing.T) {
	stub := &interactiveStub{}
	var out strings.Builder
	if err := recoverFollowOutput(context.Background(), stub, &replWatch{}, &out, InteractiveOptions{}, false); err != nil {
		t.Fatalf("recoverFollowOutput: %v", err)
	}
	if len(stub.outputRequests) != 0 || out.Len() != 0 {
		t.Fatalf("a session without the seam triggered a recovery: reads=%d out=%q", len(stub.outputRequests), out.String())
	}
}

// TestTerminalEditorSkipsTheStopLabelForAnEndedStream proves a stream that
// already reported its own end prints no second, contradictory stop message.
func TestTerminalEditorSkipsTheStopLabelForAnEndedStream(t *testing.T) {
	records := make(chan protocol.OutputFollowRecord, 2)
	records <- protocol.OutputFollowRecord{End: true, ErrorCode: "consumer_overflow"}
	close(records)
	session := newRecoverySession(records)
	defer session.Stop()
	waitEnded(t, session)
	var out strings.Builder
	editor := NewTerminalEditor(&editorTestInput{Reader: strings.NewReader("x\r")}, &out, func() int { return 40 }, func() (func() error, error) {
		return func() error { return nil }, nil
	})
	if _, _, err := editor.ReadLineWithWatch(context.Background(), "workspace> ", false, 32, session); err != nil {
		t.Fatalf("ReadLineWithWatch: %v", err)
	}
	if strings.Contains(out.String(), "follow stopped") {
		t.Fatalf("an ended stream printed a stop label: %q", out.String())
	}
}

// TestTerminalEditorKeepsTheStopLabelForALiveStream proves the suppression is
// specific to an ended stream, so a keypress that really stopped a live tail
// still tells the operator.
func TestTerminalEditorKeepsTheStopLabelForALiveStream(t *testing.T) {
	records := make(chan protocol.OutputFollowRecord)
	session := newRecoverySession(records)
	defer session.Stop()
	var out strings.Builder
	editor := NewTerminalEditor(&editorTestInput{Reader: strings.NewReader("x\r")}, &out, func() int { return 40 }, func() (func() error, error) {
		return func() error { return nil }, nil
	})
	if _, _, err := editor.ReadLineWithWatch(context.Background(), "workspace> ", false, 32, session); err != nil {
		t.Fatalf("ReadLineWithWatch: %v", err)
	}
	if !strings.Contains(out.String(), "follow stopped") {
		t.Fatalf("a live stream lost its stop label: %q", out.String())
	}
}
