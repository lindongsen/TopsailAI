package genericcli

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"strings"
	"testing"
	"time"

	"topsailai_agent_cluster/internal/protocol"
	"topsailai_agent_cluster/internal/providercli"
)

// streamHelperEnv selects what the re-executed test binary writes to stdout.
const streamHelperEnv = "AGENT_CLUSTER_STREAM_HELPER"

// TestStreamHelperProcess is the child half of the interrupt guard. It writes one
// Provider CLI stream to stdout and exits before the test framework prints its own
// summary, so scanStream never sees a non-frame line.
func TestStreamHelperProcess(t *testing.T) {
	mode := os.Getenv(streamHelperEnv)
	if mode == "" {
		t.Skip("helper process only")
	}
	switch mode {
	case "no-end":
		fmt.Println(streamLine(providercli.FrameStarted, 1))
		fmt.Println(streamLine(providercli.FrameRecord, 2))
	case "complete":
		fmt.Println(streamLine(providercli.FrameStarted, 1))
		fmt.Println(streamLine(providercli.FrameRecord, 2))
		fmt.Println(streamLine(providercli.FrameEnd, 3))
	case "many-records":
		// Write far more records than the runner's max_records, then end the
		// stream normally. A live follow is bounded by bytes and by its deadline,
		// so this stream is healthy and must complete: a record count would end it
		// with an error that names the provider.
		fmt.Println(streamLine(providercli.FrameStarted, 1))
		for sequence := int64(2); sequence <= 41; sequence++ {
			fmt.Println(streamLine(providercli.FrameRecord, sequence))
		}
		fmt.Println(streamLine(providercli.FrameEnd, 42))
	case "empty":
		// Write nothing at all, so the stream ends before any frame arrives.
	case "hold":
		// Write a started frame and one record, then stay alive well past the
		// deadline the caller sets. The stream is therefore still open when the
		// deadline fires, which is the only way to reach the branch that decides
		// whether a stopped stream is a cancellation or a provider fault.
		fmt.Println(streamLine(providercli.FrameStarted, 1))
		fmt.Println(streamLine(providercli.FrameRecord, 2))
		time.Sleep(10 * time.Second)
	}
	os.Exit(0)
}

// streamHelperRunner builds a runner that re-executes this test binary as the
// Provider CLI, so invokeStream runs against a real child process.
func streamHelperRunner(t *testing.T, mode string) *processRunner {
	t.Helper()
	executable, err := os.Executable()
	if err != nil {
		t.Fatalf("resolve test executable: %v", err)
	}
	environment := make([]string, 0, len(os.Environ())+1)
	for _, setting := range os.Environ() {
		if !strings.HasPrefix(setting, streamHelperEnv+"=") {
			environment = append(environment, setting)
		}
	}
	environment = append(environment, streamHelperEnv+"="+mode)
	runner, err := newProcessRunner(runnerConfig{
		executable:     executable,
		args:           []string{"-test.run=^TestStreamHelperProcess$", "-test.count=1"},
		environment:    environment,
		timeout:        20 * time.Second,
		maxStdinBytes:  1 << 20,
		maxStdoutBytes: 1 << 20,
		maxStderrBytes: 1 << 20,
		maxRecords:     10,
	})
	if err != nil {
		t.Fatalf("build helper runner: %v", err)
	}
	return runner
}

// followRequest builds one valid follow_output request for the helper runner.
func followRequest() providercli.Request {
	return providercli.Request{
		Version:      providercli.Version{Protocol: providercli.ProtocolName, Major: providercli.ProtocolMajor, Minor: providercli.ProtocolMinor},
		RequestID:    "follow-1",
		AdapterID:    "a",
		Function:     providercli.FunctionFollowOutput,
		DeadlineAtMS: time.Now().Add(30 * time.Second).UnixMilli(),
		Budget:       providercli.Budget{MaxStdoutBytes: 1 << 20, MaxStderrBytes: 1 << 20, MaxRecords: 10},
		Target:       &providercli.Target{ResourceKind: protocol.ResourceSession, ProviderResourceKey: "provider-session"},
		Payload:      json.RawMessage(`{"max_bytes":1024,"max_lines":10}`),
	}
}

// TestInvokeStreamInterruptsOnEOFWithoutEnd proves the link that turns a stream
// which stops without an end frame into an error. scanStream returns nil when the
// reader simply ends, so only the Finish call in invokeStream distinguishes an
// interrupted stream from a complete one. Without it the caller sees a clean end
// and reports success.
func TestInvokeStreamInterruptsOnEOFWithoutEnd(t *testing.T) {
	err := streamHelperRunner(t, "no-end").invokeStream(context.Background(), followRequest(), func(providercli.StreamFrame) error { return nil })
	if err == nil {
		t.Fatalf("a stream that stopped without an end frame returned nil, so an interrupted stream looks successful")
	}
	if !strings.Contains(err.Error(), "stream_interrupted") {
		t.Fatalf("got error %v, want the stream_interrupted message", err)
	}
}

// TestInvokeStreamInterruptsOnEmptyStream covers the other half of the interrupt
// rule: a stream that ends before any frame arrives must report that it ended
// before the started frame, not the generic interrupt message. The two Finish
// branches are separate, so a guard that only exercises a stream with a started
// frame never reaches this one.
func TestInvokeStreamInterruptsOnEmptyStream(t *testing.T) {
	err := streamHelperRunner(t, "empty").invokeStream(context.Background(), followRequest(), func(providercli.StreamFrame) error { return nil })
	if err == nil {
		t.Fatalf("an empty stream returned nil, so a stream that never started looks successful")
	}
	if !strings.Contains(err.Error(), "stream ended before started frame") {
		t.Fatalf("got error %v, want the ended-before-started message", err)
	}
}

// TestInvokeStreamReportsADeadlineAsDeadlineExceeded proves a stream stopped by
// the deadline surfaces the deadline sentinel rather than being reported as a
// provider fault.
//
// The deadline kills the process group, so the stream ends at EOF without a
// terminal frame and the validator reports a truncated stream. That truncation is
// the consequence of the stop. Reporting it as a provider fault told the operator
// the provider had failed whenever a follow was held longer than the configured
// timeout, which is the ordinary case for a live tail.
//
// The adapter deliberately does not decide the Cluster code: it reports the
// sentinel and the Endpoint names it. This test therefore asserts only that the
// sentinel survives, which is what makes the Endpoint's follow_timeout branch
// reachable. It was previously named "...AsCancelled", which described the old
// single-code behaviour and would have kept that wording alive after the split.
func TestInvokeStreamReportsADeadlineAsDeadlineExceeded(t *testing.T) {
	request := followRequest()
	request.DeadlineAtMS = time.Now().Add(300 * time.Millisecond).UnixMilli()
	err := streamHelperRunner(t, "hold").invokeStream(context.Background(), request, func(providercli.StreamFrame) error { return nil })
	if err == nil {
		t.Fatalf("a stream held past its deadline returned nil, so a stopped stream looks successful")
	}
	if !errors.Is(err, context.DeadlineExceeded) {
		t.Fatalf("got error %v, want it to wrap context.DeadlineExceeded so the Endpoint can report follow_timeout", err)
	}
}

// TestInvokeStreamKeepsAProviderFaultWhenNoDeadlineFired is the near-miss
// baseline for the classification above: a stream that ends without a terminal
// frame while the context is still live is a real provider fault and must keep
// reporting the interrupted stream. Without this case a guard that reported every
// truncated stream as cancelled would pass while hiding genuine provider faults.
func TestInvokeStreamKeepsAProviderFaultWhenNoDeadlineFired(t *testing.T) {
	err := streamHelperRunner(t, "no-end").invokeStream(context.Background(), followRequest(), func(providercli.StreamFrame) error { return nil })
	if err == nil {
		t.Fatalf("a stream that stopped without an end frame returned nil")
	}
	if errors.Is(err, context.DeadlineExceeded) || errors.Is(err, context.Canceled) {
		t.Fatalf("got error %v, want a provider fault because no deadline fired", err)
	}
	if !strings.Contains(err.Error(), "stream_interrupted") {
		t.Fatalf("got error %v, want the stream_interrupted message", err)
	}
}

// TestInvokeStreamAcceptsCompleteStream is the near-miss baseline: a stream with
// exactly one end frame must still succeed, so a guard that rejects everything
// cannot pass.
func TestInvokeStreamAcceptsCompleteStream(t *testing.T) {
	var records int
	err := streamHelperRunner(t, "complete").invokeStream(context.Background(), followRequest(), func(frame providercli.StreamFrame) error {
		if frame.Type == providercli.FrameRecord {
			records++
		}
		return nil
	})
	if err != nil {
		t.Fatalf("a complete stream was rejected: %v", err)
	}
	if records != 1 {
		t.Fatalf("forwarded %d records, want 1", records)
	}
}

// TestInvokeStreamCompletesAStreamLongerThanMaxRecords proves the record budget
// does not end a healthy stream, through a real child process rather than the
// scanner alone.
//
// The scanner-level guard proves scanStream does not count records. This one
// proves the whole invokeStream path agrees: the process is not killed, the
// terminal frame is accepted, and the caller sees success. A record count
// reintroduced anywhere between the scanner and the caller would end a 40-record
// tail with an error while the provider had answered correctly.
func TestInvokeStreamCompletesAStreamLongerThanMaxRecords(t *testing.T) {
	var records int
	err := streamHelperRunner(t, "many-records").invokeStream(context.Background(), followRequest(), func(frame providercli.StreamFrame) error {
		if frame.Type == providercli.FrameRecord {
			records++
		}
		return nil
	})
	if err != nil {
		t.Fatalf("a healthy stream carrying %d records was rejected with max_records 10: %v", records, err)
	}
	if records != 40 {
		t.Fatalf("forwarded %d records, want all 40", records)
	}
}

// TestInvokeStreamUsesTheFollowBudgetNotTheCallTimeout proves the follow budget
// actually bounds the child process, rather than being stored and ignored.
//
// The request deadline is set far in the future, so the only bound that can stop
// this stream is the follow budget. A test that set both would pass even if the
// follow budget were never read, because the request deadline would explain the
// stop. This is the composed proof for the field: the earlier defect was a
// parameter threaded through every layer with no consumer, and a distinctive
// value is the only way to tell "used" from "forwarded".
func TestInvokeStreamUsesTheFollowBudgetNotTheCallTimeout(t *testing.T) {
	runner := streamHelperRunner(t, "hold")
	runner.config.followTimeout = 300 * time.Millisecond
	runner.config.timeout = 30 * time.Second
	request := followRequest()
	request.DeadlineAtMS = time.Now().Add(30 * time.Second).UnixMilli()
	started := time.Now()
	err := runner.invokeStream(context.Background(), request, func(providercli.StreamFrame) error { return nil })
	elapsed := time.Since(started)
	if err == nil {
		t.Fatalf("a stream held past the follow budget returned nil")
	}
	if !errors.Is(err, context.DeadlineExceeded) {
		t.Fatalf("got error %v, want the deadline sentinel", err)
	}
	// The call timeout is 30s and the helper holds for 10s, so an elapsed time
	// near the follow budget proves the follow budget is the bound in force. A
	// generous ceiling keeps the assertion about which budget applied rather than
	// about scheduling precision.
	if elapsed > 5*time.Second {
		t.Fatalf("stream ran %s, so the call timeout bounded it instead of the follow budget", elapsed)
	}
}
