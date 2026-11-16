package genericcli

import (
	"errors"
	"fmt"
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/adapter"
	"topsailai_agent_cluster/internal/providercli"
)

// streamLine renders one Provider CLI JSON Lines frame for the lifecycle guard.
func streamLine(frameType string, sequence int64) string {
	switch frameType {
	case providercli.FrameRecord:
		return fmt.Sprintf(
			`{"protocol":%q,"major":%d,"minor":%d,"request_id":"follow-1","type":%q,"sequence":%d,"observed_at_ms":1000,"record":{"lines":["x"]}}`,
			providercli.ProtocolName, providercli.ProtocolMajor, providercli.ProtocolMinor, frameType, sequence,
		)
	default:
		return fmt.Sprintf(
			`{"protocol":%q,"major":%d,"minor":%d,"request_id":"follow-1","type":%q,"sequence":%d}`,
			providercli.ProtocolName, providercli.ProtocolMajor, providercli.ProtocolMinor, frameType, sequence,
		)
	}
}

// scanRunner builds a runner whose only purpose is to drive scanStream.
func scanRunner(maxRecords int64) *processRunner {
	return &processRunner{config: runnerConfig{maxRecords: maxRecords, maxStdoutBytes: 1 << 20}}
}

// scanLines feeds the given frames through scanStream and returns its error.
func scanLines(t *testing.T, runner *processRunner, lines []string) error {
	t.Helper()
	validator, err := providercli.NewStreamValidator("follow-1")
	if err != nil {
		t.Fatalf("new stream validator: %v", err)
	}
	body := strings.Join(lines, "\n") + "\n"
	return runner.scanStream(strings.NewReader(body), validator, func(providercli.StreamFrame) error { return nil })
}

// TestScanStreamAcceptsMoreRecordsThanMaxRecords pins that a live follow is not
// capped by record count. The REPL asks for 300 trailing lines while the Endpoint
// used to allow 128 records, so the old counter ended every session-scope tail with
// a provider_error that named the wrong component. A record count is deliberately
// not accumulated, so a stream longer than max_records must complete normally.
func TestScanStreamAcceptsMoreRecordsThanMaxRecords(t *testing.T) {
	const maxRecords = 3
	const records = 40
	lines := []string{streamLine(providercli.FrameStarted, 1)}
	for sequence := int64(2); sequence <= records+1; sequence++ {
		lines = append(lines, streamLine(providercli.FrameRecord, sequence))
	}
	lines = append(lines, streamLine(providercli.FrameEnd, records+2))
	if err := scanLines(t, scanRunner(maxRecords), lines); err != nil {
		t.Fatalf("a stream carrying %d records was rejected with max_records %d: %v", records, maxRecords, err)
	}
}

// TestScanStreamLabelsByteBudgetAsOutputLimit pins that exhausting the local byte
// budget is reported as a local bound rather than a provider failure. The sentinel
// is what lets the Endpoint name the real cause, so a plain error here would send
// the operator to investigate a provider that behaved correctly.
func TestScanStreamLabelsByteBudgetAsOutputLimit(t *testing.T) {
	runner := &processRunner{config: runnerConfig{maxRecords: 1000, maxStdoutBytes: 64}}
	lines := []string{streamLine(providercli.FrameStarted, 1)}
	for sequence := int64(2); sequence <= 20; sequence++ {
		lines = append(lines, streamLine(providercli.FrameRecord, sequence))
	}
	lines = append(lines, streamLine(providercli.FrameEnd, 21))
	err := scanLines(t, runner, lines)
	if err == nil {
		t.Fatal("a stream exceeding the byte budget was accepted")
	}
	if !errors.Is(err, adapter.ErrOutputLimit) {
		t.Fatalf("got error %v, want it to wrap adapter.ErrOutputLimit", err)
	}
	if !strings.Contains(err.Error(), "byte limit exceeded") {
		t.Fatalf("got error %v, want the byte limit message", err)
	}
}

// TestScanStreamRequiresOneStartSequence proves the two start rules are distinct
// branches: a record before any start and a second start report different errors,
// so neither can mask the other.
func TestScanStreamRequiresOneStartSequence(t *testing.T) {
	beforeStart := scanLines(t, scanRunner(10), []string{streamLine(providercli.FrameRecord, 1)})
	if beforeStart == nil || !strings.Contains(beforeStart.Error(), "stream must begin with started frame") {
		t.Fatalf("a record before started reported %v, want the begin-with-started message", beforeStart)
	}

	duplicateStart := scanLines(t, scanRunner(10), []string{
		streamLine(providercli.FrameStarted, 1),
		streamLine(providercli.FrameStarted, 2),
	})
	if duplicateStart == nil || !strings.Contains(duplicateStart.Error(), "stream contains duplicate started frame") {
		t.Fatalf("a second started reported %v, want the duplicate-started message", duplicateStart)
	}

	if beforeStart.Error() == duplicateStart.Error() {
		t.Fatalf("both start violations reported %q, so one branch is masking the other", beforeStart)
	}

	baseline := []string{
		streamLine(providercli.FrameStarted, 1),
		streamLine(providercli.FrameRecord, 2),
		streamLine(providercli.FrameEnd, 3),
	}
	if err := scanLines(t, scanRunner(10), baseline); err != nil {
		t.Fatalf("a stream with exactly one start was rejected: %v", err)
	}
}

// TestScanStreamRequiresExactlyOneEnd proves a second end is rejected and that a
// complete stream still finishes cleanly.
func TestScanStreamRequiresExactlyOneEnd(t *testing.T) {
	secondEnd := scanLines(t, scanRunner(10), []string{
		streamLine(providercli.FrameStarted, 1),
		streamLine(providercli.FrameEnd, 2),
		streamLine(providercli.FrameEnd, 3),
	})
	if secondEnd == nil || !strings.Contains(secondEnd.Error(), "stream frame received after terminal frame") {
		t.Fatalf("a second end reported %v, want the after-terminal message", secondEnd)
	}

	validator, err := providercli.NewStreamValidator("follow-1")
	if err != nil {
		t.Fatalf("new stream validator: %v", err)
	}
	complete := []string{
		streamLine(providercli.FrameStarted, 1),
		streamLine(providercli.FrameRecord, 2),
		streamLine(providercli.FrameEnd, 3),
	}
	if err := scanLines(t, scanRunner(10), complete); err != nil {
		t.Fatalf("a complete stream was rejected: %v", err)
	}
	for _, line := range complete {
		frame, decodeErr := providercli.DecodeStreamFrame([]byte(line))
		if decodeErr != nil {
			t.Fatalf("decode %s: %v", line, decodeErr)
		}
		if acceptErr := validator.Accept(frame); acceptErr != nil {
			t.Fatalf("accept %s: %v", line, acceptErr)
		}
	}
	if err := validator.Finish(); err != nil {
		t.Fatalf("a stream with exactly one end did not finish: %v", err)
	}

	interrupted, err := providercli.NewStreamValidator("follow-1")
	if err != nil {
		t.Fatalf("new stream validator: %v", err)
	}
	for _, line := range complete[:2] {
		frame, decodeErr := providercli.DecodeStreamFrame([]byte(line))
		if decodeErr != nil {
			t.Fatalf("decode %s: %v", line, decodeErr)
		}
		if acceptErr := interrupted.Accept(frame); acceptErr != nil {
			t.Fatalf("accept %s: %v", line, acceptErr)
		}
	}
	if err := interrupted.Finish(); err == nil || !strings.Contains(err.Error(), "stream_interrupted") {
		t.Fatalf("EOF before end reported %v, want the stream_interrupted message", err)
	}
}
