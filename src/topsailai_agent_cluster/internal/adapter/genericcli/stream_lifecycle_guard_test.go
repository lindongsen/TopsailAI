package genericcli

import (
	"fmt"
	"strings"
	"testing"

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

// TestScanStreamAcceptsExactlyMaxRecords pins the record bound on the streaming
// path. The counter lives in scanStream, so a configuration that is validated as
// positive but never accumulated would pass every other test in this package.
func TestScanStreamAcceptsExactlyMaxRecords(t *testing.T) {
	const maxRecords = 3
	accepted := []string{streamLine(providercli.FrameStarted, 1)}
	for sequence := int64(2); sequence <= maxRecords+1; sequence++ {
		accepted = append(accepted, streamLine(providercli.FrameRecord, sequence))
	}
	accepted = append(accepted, streamLine(providercli.FrameEnd, maxRecords+2))
	if err := scanLines(t, scanRunner(maxRecords), accepted); err != nil {
		t.Fatalf("a stream carrying exactly %d records was rejected: %v", maxRecords, err)
	}

	overflow := []string{streamLine(providercli.FrameStarted, 1)}
	for sequence := int64(2); sequence <= maxRecords+2; sequence++ {
		overflow = append(overflow, streamLine(providercli.FrameRecord, sequence))
	}
	overflow = append(overflow, streamLine(providercli.FrameEnd, maxRecords+3))
	err := scanLines(t, scanRunner(maxRecords), overflow)
	if err == nil {
		t.Fatalf("a stream carrying %d records was accepted with max_records %d", maxRecords+1, maxRecords)
	}
	want := fmt.Sprintf("provider stream record limit exceeded: %d", maxRecords)
	if !strings.Contains(err.Error(), want) {
		t.Fatalf("got error %v, want the record limit message %q", err, want)
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
