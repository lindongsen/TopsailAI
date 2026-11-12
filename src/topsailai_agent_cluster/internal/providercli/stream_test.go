package providercli

import (
	"encoding/json"
	"strings"
	"testing"
)

func streamFrame(requestID, frameType string, sequence int64) StreamFrame {
	frame := StreamFrame{
		Version:   validVersion(),
		RequestID: requestID,
		Type:      frameType,
		Sequence:  sequence,
	}
	if frameType == FrameRecord {
		frame.ObservedAtMS = 1000
		frame.Record = json.RawMessage(`{"content":"line"}`)
	}
	return frame
}

func TestStreamValidatorAcceptsCompleteStream(t *testing.T) {
	validator, err := NewStreamValidator("follow-1")
	if err != nil {
		t.Fatal(err)
	}
	frames := []StreamFrame{
		streamFrame("follow-1", FrameStarted, 1),
		streamFrame("follow-1", FrameRecord, 2),
		streamFrame("follow-1", FrameEnd, 3),
	}
	for _, frame := range frames {
		if err := validator.Accept(frame); err != nil {
			t.Fatalf("valid frame rejected: %v", err)
		}
	}
	if err := validator.Finish(); err != nil {
		t.Fatalf("complete stream rejected: %v", err)
	}
}

func TestStreamValidatorRejectsInvalidLifecycle(t *testing.T) {
	tests := []struct {
		name   string
		frames []StreamFrame
		finish bool
		match  string
	}{
		{name: "missing start", frames: []StreamFrame{streamFrame("follow-1", FrameRecord, 1)}, match: "begin with started"},
		{name: "duplicate start", frames: []StreamFrame{streamFrame("follow-1", FrameStarted, 1), streamFrame("follow-1", FrameStarted, 2)}, match: "duplicate started"},
		{name: "duplicate terminal", frames: []StreamFrame{streamFrame("follow-1", FrameStarted, 1), streamFrame("follow-1", FrameEnd, 2), streamFrame("follow-1", FrameEnd, 3)}, match: "after terminal"},
		{name: "post terminal record", frames: []StreamFrame{streamFrame("follow-1", FrameStarted, 1), streamFrame("follow-1", FrameEnd, 2), streamFrame("follow-1", FrameRecord, 3)}, match: "after terminal"},
		{name: "correlation mismatch", frames: []StreamFrame{streamFrame("follow-2", FrameStarted, 1)}, match: "does not match"},
		{name: "sequence gap", frames: []StreamFrame{streamFrame("follow-1", FrameStarted, 1), streamFrame("follow-1", FrameRecord, 3)}, match: "does not follow"},
		{name: "EOF before start", finish: true, match: "before started"},
		{name: "EOF before terminal", frames: []StreamFrame{streamFrame("follow-1", FrameStarted, 1), streamFrame("follow-1", FrameRecord, 2)}, finish: true, match: "stream_interrupted"},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			validator, err := NewStreamValidator("follow-1")
			if err != nil {
				t.Fatal(err)
			}
			for _, frame := range test.frames {
				err = validator.Accept(frame)
				if err != nil {
					break
				}
			}
			if err == nil && test.finish {
				err = validator.Finish()
			}
			if err == nil || !strings.Contains(err.Error(), test.match) {
				t.Fatalf("got error %v, want match %q", err, test.match)
			}
		})
	}
}

func TestDecodeStreamFrameRejectsAuthorityField(t *testing.T) {
	frame := `{"protocol":"agent-cluster-adapter","major":1,"minor":0,"request_id":"follow-1","type":"end","sequence":1,"command_revision":3}`
	if _, err := DecodeStreamFrame([]byte(frame)); err == nil || !strings.Contains(err.Error(), "unknown field") {
		t.Fatalf("authority field was not rejected: %v", err)
	}
}

func TestDecodeStreamFrameRequiresAndForbidsFieldPresence(t *testing.T) {
	tests := []struct {
		name  string
		frame string
		match string
	}{
		{
			name:  "started forbids explicit false truncation",
			frame: `{"protocol":"agent-cluster-adapter","major":1,"minor":0,"request_id":"follow-1","type":"started","sequence":1,"truncated":false}`,
			match: "truncated",
		},
		{
			name:  "record requires observation time",
			frame: `{"protocol":"agent-cluster-adapter","major":1,"minor":0,"request_id":"follow-1","type":"record","sequence":1,"record":{}}`,
			match: "observed_at_ms",
		},
		{
			name:  "terminal error requires retryable",
			frame: `{"protocol":"agent-cluster-adapter","major":1,"minor":0,"request_id":"follow-1","type":"end","sequence":1,"error":{"code":"failed","message":"failed","effect_certainty":"unknown"}}`,
			match: "retryable",
		},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			if _, err := DecodeStreamFrame([]byte(test.frame)); err == nil || !strings.Contains(err.Error(), test.match) {
				t.Fatalf("got error %v, want match %q", err, test.match)
			}
		})
	}
}
