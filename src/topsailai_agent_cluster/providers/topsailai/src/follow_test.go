package main

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"reflect"
	"strings"
	"testing"
	"time"
)

type fakeStreamRunner struct {
	t       *testing.T
	rows    []followRecord
	err     error
	args    []string
	limit   int
	runCall int
}

func (r *fakeStreamRunner) Run(_ context.Context, args []string, _ []byte) ([]byte, []byte, error) {
	r.runCall++
	if !reflect.DeepEqual(args, []string{"workspace", "list", "--json", "--local"}) {
		r.t.Fatalf("unexpected unary args: %v", args)
	}
	return []byte(`{"items":[{"session_id":"s-1","filename":"row","pid":77}]}`), nil, nil
}

func (r *fakeStreamRunner) Follow(_ context.Context, args []string, limit int, emit func(followRecord) error) error {
	r.args = append([]string(nil), args...)
	r.limit = limit
	for _, row := range r.rows {
		if err := emit(row); err != nil {
			return err
		}
	}
	return r.err
}

func followRequest(t *testing.T, payload string) request {
	t.Helper()
	value := validRequest(functionFollowOutput)
	value.Target = sessionTarget(t)
	value.Payload = json.RawMessage(payload)
	return value
}

func decodeFrames(t *testing.T, output []byte) []streamFrame {
	t.Helper()
	decoder := json.NewDecoder(bytes.NewReader(output))
	var frames []streamFrame
	for decoder.More() {
		var frame streamFrame
		if err := decoder.Decode(&frame); err != nil {
			t.Fatalf("decode frame: %v output=%q", err, output)
		}
		frames = append(frames, frame)
	}
	return frames
}

func TestFollowOutputEmitsStrictLifecycle(t *testing.T) {
	runner := &fakeStreamRunner{t: t, rows: []followRecord{{Line: "first"}, {Line: "中", Truncated: true}}}
	provider := fixedProvider(runner)
	var output bytes.Buffer
	if err := provider.followOutput(context.Background(), followRequest(t, `{"max_bytes":64,"max_lines":7}`), &output); err != nil {
		t.Fatalf("follow output: %v", err)
	}
	frames := decodeFrames(t, output.Bytes())
	if len(frames) != 4 {
		t.Fatalf("frames=%+v", frames)
	}
	for index, frame := range frames {
		if frame.RequestID != "request-1" || frame.Sequence != int64(index+1) || frame.Protocol != protocolName || frame.Major != protocolMajor || frame.Minor != protocolMinor {
			t.Fatalf("frame[%d]=%+v", index, frame)
		}
	}
	if frames[0].Type != frameStarted || frames[1].Type != frameRecord || frames[2].Type != frameRecord || frames[3].Type != frameEnd || frames[3].Error != nil {
		t.Fatalf("frames=%+v", frames)
	}
	if frames[1].ObservedAtMS != 1700000000123 || frames[1].Truncated || !frames[2].Truncated {
		t.Fatalf("record frames=%+v", frames[1:3])
	}
	var record struct {
		Lines []string `json:"lines"`
	}
	if err := decodeStrict(frames[2].Record, &record); err != nil || !reflect.DeepEqual(record.Lines, []string{"中"}) {
		t.Fatalf("record=%+v err=%v", record, err)
	}
	wantArgs := []string{"runtime", "logs", "-s", "s-1", "-p", "77", "-n", "7", "--follow"}
	if !reflect.DeepEqual(runner.args, wantArgs) || runner.limit != 64 {
		t.Fatalf("args=%v limit=%d", runner.args, runner.limit)
	}
}

func TestFollowOutputReportsCancellationAndFailureInTerminalFrame(t *testing.T) {
	for name, streamErr := range map[string]error{
		"cancelled": context.Canceled,
		"failed":    errors.New("child exited 9"),
	} {
		t.Run(name, func(t *testing.T) {
			runner := &fakeStreamRunner{t: t, err: streamErr}
			var output bytes.Buffer
			if err := fixedProvider(runner).followOutput(context.Background(), followRequest(t, `{}`), &output); err != nil {
				t.Fatalf("follow output: %v", err)
			}
			frames := decodeFrames(t, output.Bytes())
			if len(frames) != 2 || frames[0].Type != frameStarted || frames[1].Type != frameEnd || frames[1].Error == nil {
				t.Fatalf("frames=%+v", frames)
			}
			if name == "cancelled" && frames[1].Error.Code != "cancelled" {
				t.Fatalf("error=%+v", frames[1].Error)
			}
			if name == "failed" && !strings.Contains(frames[1].Error.Message, "child exited 9") {
				t.Fatalf("error=%+v", frames[1].Error)
			}
		})
	}
}

func TestFollowOutputUsesRequestDeadlineAndWritesTerminalError(t *testing.T) {
	runner := &blockingStreamRunner{fakeStreamRunner: fakeStreamRunner{t: t}}
	request := followRequest(t, `{}`)
	request.DeadlineAtMS = 1_700_000_000_124
	var output bytes.Buffer
	if err := fixedProvider(runner).followOutput(context.Background(), request, &output); err != nil {
		t.Fatalf("follow output: %v", err)
	}
	frames := decodeFrames(t, output.Bytes())
	// The request deadline expiring is a timeout, not a cancellation: nobody
	// stopped the stream, it reached its own bound. This assertion used to expect
	// "cancelled", which encoded the defect rather than guarding against it, so it
	// is replaced here instead of being kept beside a new test.
	if len(frames) != 2 || frames[1].Type != frameEnd || frames[1].Error == nil || frames[1].Error.Code != "follow_timeout" {
		t.Fatalf("frames=%+v", frames)
	}
}

type blockingStreamRunner struct {
	fakeStreamRunner
}

func (r *blockingStreamRunner) Follow(ctx context.Context, args []string, limit int, _ func(followRecord) error) error {
	r.args = append([]string(nil), args...)
	r.limit = limit
	select {
	case <-ctx.Done():
		return ctx.Err()
	case <-time.After(time.Second):
		return errors.New("follow context was not bounded")
	}
}

func TestFollowOutputRejectsInvalidPayloadBeforeBusinessCLI(t *testing.T) {
	runner := &fakeStreamRunner{t: t}
	var output bytes.Buffer
	if err := fixedProvider(runner).followOutput(context.Background(), followRequest(t, `{"max_bytes":1,"unknown":true}`), &output); err != nil {
		t.Fatalf("follow output: %v", err)
	}
	frames := decodeFrames(t, output.Bytes())
	if len(frames) != 2 || frames[1].Error == nil || frames[1].Error.Code != "invalid_request" {
		t.Fatalf("frames=%+v", frames)
	}
	if runner.runCall != 0 || runner.args != nil {
		t.Fatalf("business CLI called: run=%d follow=%v", runner.runCall, runner.args)
	}
}

func TestScanFollowLinesTruncatesUTF8AndContinues(t *testing.T) {
	var rows []followRecord
	err := scanFollowLines(strings.NewReader("中中中\nok\n"), 4, func(row followRecord) error {
		rows = append(rows, row)
		return nil
	})
	if err != nil {
		t.Fatal(err)
	}
	if len(rows) != 2 || rows[0].Line != "中" || !rows[0].Truncated || rows[1].Line != "ok" || rows[1].Truncated {
		t.Fatalf("rows=%+v", rows)
	}
}

func TestFollowEnvironmentForcesUnbuffered(t *testing.T) {
	environment := followEnvironment("/usr/bin/topsailai", []string{"PATH=/bin", "PYTHONUNBUFFERED=0", "PYTHONUNBUFFERED="})
	count := 0
	for _, entry := range environment {
		if strings.HasPrefix(entry, "PYTHONUNBUFFERED=") {
			count++
			if entry != "PYTHONUNBUFFERED=1" {
				t.Fatalf("entry=%q", entry)
			}
		}
	}
	if count != 1 {
		t.Fatalf("PYTHONUNBUFFERED count=%d environment=%v", count, environment)
	}
}
