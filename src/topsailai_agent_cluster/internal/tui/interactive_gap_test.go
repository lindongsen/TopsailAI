package tui

import (
	"bytes"
	"context"
	"errors"
	"strings"
	"testing"
	"time"

	"topsailai_agent_cluster/internal/protocol"
)

func TestInteractiveWriterFailureReturnsWithoutPanic(t *testing.T) {
	stub := &interactiveStub{}
	err := RunInteractive(context.Background(), stub, strings.NewReader("help\n"), &failingWriter{}, &strings.Builder{}, InteractiveOptions{})
	if err == nil || err.Error() != "write failed" {
		t.Fatalf("unexpected writer error: %v", err)
	}
}

type failingWriter struct{}

func (*failingWriter) Write([]byte) (int, error) { return 0, errors.New("write failed") }

func TestInteractiveContinuesAfterRecoveredCommandFailure(t *testing.T) {
	stub := &interactiveStub{endpoints: []protocol.Endpoint{{EndpointID: "endpoint-1"}}, reports: map[string]protocol.InventoryReport{"endpoint-1": testInventory()}, failList: true}
	var output, errorsOut strings.Builder
	if err := RunInteractive(context.Background(), stub, strings.NewReader("list\nhelp\nquit\n"), &output, &errorsOut, InteractiveOptions{}); err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(errorsOut.String(), "temporary list failure") {
		t.Fatalf("missing recovered failure: %q", errorsOut.String())
	}
	if !strings.Contains(output.String(), "Current scope:") {
		t.Fatalf("loop did not continue to help: %q", output.String())
	}
}

func TestInteractiveExitAliasesReturnAfterPrompt(t *testing.T) {
	for _, command := range []string{"quit\n", "exit\n", ""} {
		var output, errorsOut strings.Builder
		if err := RunInteractive(context.Background(), &interactiveStub{}, strings.NewReader(command), &output, &errorsOut, InteractiveOptions{}); err != nil {
			t.Fatalf("command %q: %v", command, err)
		}
	}
}

func TestSafeWriterDoesNotLeakControlsAcrossWrites(t *testing.T) {
	var output strings.Builder
	writer := newSafeWriter(&output)
	if _, err := writer.Write([]byte("prefix\x1b")); err != nil {
		t.Fatal(err)
	}
	if _, err := writer.Write([]byte("[31msecret\r\n")); err != nil {
		t.Fatal(err)
	}
	if strings.ContainsAny(output.String(), "\x1b\r") {
		t.Fatalf("control sequence leaked across writes: %q", output.String())
	}
}

func TestSafeWriterFiltersUnsafeUnicodeAndOSC(t *testing.T) {
	input := "ok\x00\x1b[31mred\x1b]0;title\a\u202e\u200bend"
	var output strings.Builder
	writer := newSafeWriter(&output)
	for _, chunk := range [][]byte{[]byte(input[:5]), []byte(input[5:11]), []byte(input[11:])} {
		if _, err := writer.Write(chunk); err != nil {
			t.Fatal(err)
		}
	}
	if err := writer.Flush(); err != nil {
		t.Fatal(err)
	}
	got := output.String()
	if strings.Contains(got, "\x00") || strings.Contains(got, "\x1b") || strings.Contains(got, "title") || strings.Contains(got, "\u202e") || strings.Contains(got, "\u200b") {
		t.Fatalf("unsafe content leaked: %q", got)
	}
	if got != "ok�redend" {
		t.Fatalf("unexpected sanitized output: %q", got)
	}
}

func TestSafeWriterPreservesChunkedUTF8(t *testing.T) {
	input := "ASCII caf\u00e9 \u4e16\u754c \U0001f44b e\u0301\n\tend"
	for width := 1; width <= 3; width++ {
		var output strings.Builder
		writer := newSafeWriter(&output)
		for offset := 0; offset < len(input); {
			end := offset + width
			if end > len(input) {
				end = len(input)
			}
			if _, err := writer.Write([]byte(input[offset:end])); err != nil {
				t.Fatal(err)
			}
			offset = end
		}
		if err := writer.Flush(); err != nil {
			t.Fatal(err)
		}
		if output.String() != input {
			t.Fatalf("width %d output=%q want=%q", width, output.String(), input)
		}
	}
}

func TestSafeWriterFiltersSplitCSIAndOSC(t *testing.T) {
	for _, testCase := range []struct {
		input string
		want  string
	}{
		{"before\x1b[31msecret", "beforesecret"},
		{"before\x1b]0;title\aafter", "beforeafter"},
		{"before\x1b]8;;url\x1b\\after", "beforeafter"},
	} {
		for split := 0; split <= len(testCase.input); split++ {
			var output strings.Builder
			writer := newSafeWriter(&output)
			if _, err := writer.Write([]byte(testCase.input[:split])); err != nil {
				t.Fatal(err)
			}
			if _, err := writer.Write([]byte(testCase.input[split:])); err != nil {
				t.Fatal(err)
			}
			if err := writer.Flush(); err != nil {
				t.Fatal(err)
			}
			if output.String() != testCase.want {
				t.Fatalf("input %q split %d output=%q want=%q", testCase.input, split, output.String(), testCase.want)
			}
		}
	}
}

func TestSafeWriterFlushDropsIncompleteSequenceAndFiltersBidi(t *testing.T) {
	var output strings.Builder
	writer := newSafeWriter(&output)
	if _, err := writer.Write([]byte("ok\x1b]0;unterminated")); err != nil {
		t.Fatal(err)
	}
	if err := writer.Flush(); err != nil {
		t.Fatal(err)
	}
	bidi := string([]rune{0x202a, 0x202b, 0x202c, 0x202d, 0x202e, 0x2066, 0x2067, 0x2068, 0x2069, 0x200e, 0x200f, 0x061c})
	if _, err := writer.Write([]byte(bidi + "done")); err != nil {
		t.Fatal(err)
	}
	if err := writer.Flush(); err != nil {
		t.Fatal(err)
	}
	if output.String() != "okdone" {
		t.Fatalf("output=%q want=%q", output.String(), "okdone")
	}
	if writer.sequenceSize != 0 || writer.state != terminalNormal || len(writer.utf8Pending) != 0 {
		t.Fatalf("state not flushed: state=%d sequence=%d pending=%d", writer.state, writer.sequenceSize, len(writer.utf8Pending))
	}
}

func TestSafeWriterBoundsUnterminatedSequence(t *testing.T) {
	var output strings.Builder
	writer := newSafeWriter(&output)
	data := append([]byte("prefix\x1b]"), bytes.Repeat([]byte{'x'}, 10000)...)
	if _, err := writer.Write(data); err != nil {
		t.Fatal(err)
	}
	if writer.sequenceSize > maxTerminalSequenceBytes {
		t.Fatalf("sequence size=%d exceeds limit", writer.sequenceSize)
	}
	if err := writer.Flush(); err != nil {
		t.Fatal(err)
	}
	if output.String() != "prefix" {
		t.Fatalf("unexpected bounded output=%q", output.String())
	}
}

func TestSendAdmissionUncertainRetainsID(t *testing.T) {
	stub := &uncertainAdmissionStub{inventory: freshTestInventory()}
	var output, errorsOut strings.Builder
	input := "cd ep/session-1\nsend {\"text\":\"hi\"}\ny\nstatus\nquit\n"
	if err := RunInteractive(context.Background(), stub, strings.NewReader(input), &output, &errorsOut, InteractiveOptions{}); err != nil {
		t.Fatal(err)
	}
	if stub.admit != 1 {
		t.Fatalf("POST count=%d want=1", stub.admit)
	}
	diagnostic := errorsOut.String()
	marker := "error: command "
	start := strings.Index(diagnostic, marker)
	if start < 0 {
		t.Fatalf("missing retained ID diagnostic: %q", diagnostic)
	}
	fields := strings.Fields(diagnostic[start+len("error: "):])
	if len(fields) < 8 || fields[0] != "command" || fields[2] != "result" || fields[3] != "unknown;" || fields[4] != "use" || fields[5] != "status" {
		t.Fatalf("unexpected diagnostic: %q", diagnostic)
	}
	commandID := fields[1]
	if fields[6] != commandID || stub.commands != 1 || stub.lastCommand != commandID {
		t.Fatalf("status queries=%d id=%q diagnostic_id=%q", stub.commands, stub.lastCommand, commandID)
	}
}

func TestSendWaitBudgetIndependentFromAdmissionContext(t *testing.T) {
	const marker = "admission-marker"
	parent := context.WithValue(context.Background(), waitContextMarkerKey{}, marker)
	parent, cancel := context.WithDeadline(parent, time.Now().Add(-time.Second))
	defer cancel()
	if err := parent.Err(); !errors.Is(err, context.DeadlineExceeded) {
		t.Fatalf("parent error=%v, want deadline exceeded", err)
	}

	reader := &deadlineWaitReader{parentDone: parent.Done()}
	runner := CommandRunner{API: reader}
	before := time.Now()
	result, err := runner.WaitAction(parent, ActionResult{CommandID: "cmd-1"}, protocol.Budget{WaitTimeoutMS: 100})
	after := time.Now()
	if err != nil {
		t.Fatal(err)
	}
	if result["status"] != string(protocol.StatusFinished) {
		t.Fatalf("result=%#v", result)
	}
	if reader.calls != 1 || reader.commandID != "cmd-1" {
		t.Fatalf("calls=%d commandID=%q", reader.calls, reader.commandID)
	}
	if reader.marker != marker {
		t.Fatalf("marker=%v, want %q", reader.marker, marker)
	}
	if reader.parentDone == nil || reader.childDone == nil || reader.childDone == reader.parentDone {
		t.Fatalf("parentDone=%v childDone=%v", reader.parentDone, reader.childDone)
	}
	wantMin := before.Add(100 * time.Millisecond)
	wantMax := after.Add(100 * time.Millisecond)
	if !reader.hasDeadline || reader.deadline.Before(wantMin) || reader.deadline.After(wantMax) {
		t.Fatalf("deadline=%v, want between %v and %v", reader.deadline, wantMin, wantMax)
	}
}

func TestSelectedAdapterFreshnessRejectsUse(t *testing.T) {
	for _, testCase := range []struct {
		name  string
		adapt protocol.AdapterSummary
		want  string
	}{
		{name: "stale", adapt: protocol.AdapterSummary{AdapterID: "adapter-1", DataKnown: true, Stale: true, CollectionStatus: protocol.CollectionSucceeded}, want: "stale=true"},
		{name: "unknown", adapt: protocol.AdapterSummary{AdapterID: "adapter-1", DataKnown: false, CollectionStatus: protocol.CollectionSucceeded}, want: "unknown=true"},
		{name: "incomplete", adapt: protocol.AdapterSummary{AdapterID: "adapter-1", DataKnown: true, CollectionStatus: protocol.CollectionPartial}, want: "collection_status=partial"},
	} {
		t.Run(testCase.name, func(t *testing.T) {
			stub := &freshnessStub{inventory: freshTestInventoryWithAdapter(testCase.adapt)}
			var output, errorsOut strings.Builder
			if err := RunInteractive(context.Background(), stub, strings.NewReader("cd ep/session-1\nquit\n"), &output, &errorsOut, InteractiveOptions{}); err != nil {
				t.Fatal(err)
			}
			if !strings.Contains(errorsOut.String(), testCase.want) {
				t.Fatalf("errors=%q want %q", errorsOut.String(), testCase.want)
			}
		})
	}
}

func TestSelectedAdapterFreshnessChangesBeforeSend(t *testing.T) {
	stub := &freshnessStub{
		inventory: freshTestInventoryWithAdapter(protocol.AdapterSummary{AdapterID: "adapter-1", DataKnown: true, CollectionStatus: protocol.CollectionSucceeded}),
		second:    freshTestInventoryWithAdapter(protocol.AdapterSummary{AdapterID: "adapter-1", DataKnown: true, Stale: true, CollectionStatus: protocol.CollectionSucceeded}),
	}
	var output, errorsOut strings.Builder
	input := "cd ep/session-1\nsend {\"text\":\"hi\"}\ny\nquit\n"
	if err := RunInteractive(context.Background(), stub, strings.NewReader(input), &output, &errorsOut, InteractiveOptions{}); err != nil {
		t.Fatal(err)
	}
	if stub.admit != 0 {
		t.Fatalf("POST count=%d want=0", stub.admit)
	}
	if !strings.Contains(errorsOut.String(), "stale=true") {
		t.Fatalf("errors=%q", errorsOut.String())
	}
}

type uncertainAdmissionStub struct {
	interactiveStub
	inventory   protocol.InventoryReport
	admit       int
	commands    int
	lastCommand string
}

func (s *uncertainAdmissionStub) ListEndpoints(context.Context) ([]protocol.Endpoint, error) {
	return []protocol.Endpoint{{EndpointID: "ep"}}, nil
}
func (s *uncertainAdmissionStub) GetInventory(context.Context, string) (protocol.InventoryReport, error) {
	return s.inventory, nil
}
func (s *uncertainAdmissionStub) GetCapabilities(context.Context, string) (protocol.CapabilityDescriptor, error) {
	return protocol.CapabilityDescriptor{Revision: "r1", Capabilities: []protocol.Capability{{Name: protocol.OperationMessageSend}}}, nil
}
func (s *uncertainAdmissionStub) GetCommand(_ context.Context, commandID string) (map[string]any, error) {
	s.commands++
	s.lastCommand = commandID
	return map[string]any{"status": string(protocol.StatusFinished)}, nil
}
func (s *uncertainAdmissionStub) AdmitCommand(context.Context, protocol.ImmutableIntent) (map[string]any, error) {
	s.admit++
	return nil, errors.New("transport timeout")
}

func (s *uncertainAdmissionStub) ListCommands(context.Context, string, string, int) ([]map[string]any, error) {
	return nil, nil
}
func (s *uncertainAdmissionStub) GetOutput(context.Context, string, string, string, int, int) (protocol.OutputSnapshotResponse, error) {
	return protocol.OutputSnapshotResponse{}, nil
}

type waitContextMarkerKey struct{}

type deadlineWaitReader struct {
	calls       int
	commandID   string
	marker      any
	parentDone  <-chan struct{}
	childDone   <-chan struct{}
	deadline    time.Time
	hasDeadline bool
}

func (r *deadlineWaitReader) ListEndpoints(context.Context) ([]protocol.Endpoint, error) {
	return nil, nil
}
func (r *deadlineWaitReader) GetInventory(context.Context, string) (protocol.InventoryReport, error) {
	return protocol.InventoryReport{}, nil
}
func (r *deadlineWaitReader) GetCapabilities(context.Context, string) (protocol.CapabilityDescriptor, error) {
	return protocol.CapabilityDescriptor{}, nil
}
func (r *deadlineWaitReader) ListCommands(context.Context, string, string, int) ([]map[string]any, error) {
	return nil, nil
}
func (r *deadlineWaitReader) GetOutput(context.Context, string, string, string, int, int) (protocol.OutputSnapshotResponse, error) {
	return protocol.OutputSnapshotResponse{}, nil
}
func (r *deadlineWaitReader) AdmitCommand(context.Context, protocol.ImmutableIntent) (map[string]any, error) {
	return nil, nil
}
func (r *deadlineWaitReader) GetCommand(ctx context.Context, commandID string) (map[string]any, error) {
	r.calls++
	r.commandID = commandID
	r.marker = ctx.Value(waitContextMarkerKey{})
	r.childDone = ctx.Done()
	r.deadline, r.hasDeadline = ctx.Deadline()
	return map[string]any{"status": string(protocol.StatusFinished)}, nil
}

type freshnessStub struct {
	inventory protocol.InventoryReport
	second    protocol.InventoryReport
	calls     int
	admit     int
}

func (s *freshnessStub) ListEndpoints(context.Context) ([]protocol.Endpoint, error) {
	return []protocol.Endpoint{{EndpointID: "ep"}}, nil
}
func (s *freshnessStub) GetInventory(context.Context, string) (protocol.InventoryReport, error) {
	s.calls++
	if s.second.Adapters != nil && s.calls > 2 {
		return s.second, nil
	}
	return s.inventory, nil
}
func (s *freshnessStub) GetCapabilities(context.Context, string) (protocol.CapabilityDescriptor, error) {
	return protocol.CapabilityDescriptor{Revision: "r1", Capabilities: []protocol.Capability{{Name: protocol.OperationMessageSend}}}, nil
}
func (s *freshnessStub) GetCommand(context.Context, string) (map[string]any, error) {
	return map[string]any{"status": string(protocol.StatusFinished)}, nil
}
func (s *freshnessStub) ListCommands(context.Context, string, string, int) ([]map[string]any, error) {
	return nil, nil
}
func (s *freshnessStub) GetOutput(context.Context, string, string, string, int, int) (protocol.OutputSnapshotResponse, error) {
	return protocol.OutputSnapshotResponse{}, nil
}
func (s *freshnessStub) AdmitCommand(context.Context, protocol.ImmutableIntent) (map[string]any, error) {
	s.admit++
	return map[string]any{"command_id": "cmd-1"}, nil
}

func freshTestInventory() protocol.InventoryReport {
	return freshTestInventoryWithAdapter(protocol.AdapterSummary{AdapterID: "adapter-1", DataKnown: true, CollectionStatus: protocol.CollectionSucceeded})
}
func freshTestInventoryWithAdapter(adapter protocol.AdapterSummary) protocol.InventoryReport {
	return protocol.InventoryReport{ReportComplete: true, CollectionStatus: protocol.CollectionSucceeded, Adapters: []protocol.AdapterSummary{adapter}, Sessions: []protocol.Session{{SessionID: "session-1", AdapterID: "adapter-1", Generation: "generation-1", State: "running", CollectionStatus: protocol.CollectionSucceeded}}}
}

func TestSelectedSessionFreshnessRejectsInvalidReports(t *testing.T) {
	cases := []struct {
		name   string
		mutate func(*protocol.Session)
		want   string
	}{
		{name: "stale", mutate: func(session *protocol.Session) { session.Stale = true }, want: "stale=true"},
		{name: "unknown", mutate: func(session *protocol.Session) { session.Unknown = true }, want: "unknown=true"},
		{name: "failed collection", mutate: func(session *protocol.Session) { session.CollectionStatus = protocol.CollectionFailed }, want: "collection_status=failed"},
	}
	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			inventory := freshTestInventory()
			testCase.mutate(&inventory.Sessions[0])
			stub := &freshnessStub{inventory: inventory}
			var output, errorsOut strings.Builder
			if err := RunInteractive(context.Background(), stub, strings.NewReader("cd ep/session-1\nquit\n"), &output, &errorsOut, InteractiveOptions{}); err != nil {
				t.Fatal(err)
			}
			if !strings.Contains(errorsOut.String(), testCase.want) {
				t.Fatalf("errors=%q want substring %q", errorsOut.String(), testCase.want)
			}
		})
	}
}

func TestMissingAdapterSummaryDoesNotBlockFreshSession(t *testing.T) {
	inventory := protocol.InventoryReport{
		ReportComplete:   true,
		CollectionStatus: protocol.CollectionSucceeded,
		Sessions:         []protocol.Session{{SessionID: "session-1", AdapterID: "unreported-adapter", Generation: "generation-1", State: "running", CollectionStatus: protocol.CollectionSucceeded}},
	}
	stub := &freshnessStub{inventory: inventory}
	var output, errorsOut strings.Builder
	if err := RunInteractive(context.Background(), stub, strings.NewReader("cd ep/session-1\nstatus\nquit\n"), &output, &errorsOut, InteractiveOptions{}); err != nil {
		t.Fatal(err)
	}
	if errorsOut.Len() != 0 {
		t.Fatalf("unexpected errors for absent adapter summary: %q", errorsOut.String())
	}
	if !strings.Contains(output.String(), "running") {
		t.Fatalf("fresh session was not usable: %q", output.String())
	}
}

func TestSessionFreshnessInheritsInventoryCollectionStatus(t *testing.T) {
	cases := []struct {
		name       string
		inventory  string
		explicit   string
		wantError  string
		wantPrompt string
	}{
		{name: "top level succeeded", inventory: protocol.CollectionSucceeded, wantPrompt: "session[ep/-]> "},
		{name: "top level failed", inventory: protocol.CollectionFailed, wantError: "collection_status=failed"},
		{name: "top level missing", inventory: "", wantError: "collection_status="},
		{name: "explicit session succeeds", inventory: protocol.CollectionFailed, explicit: protocol.CollectionSucceeded, wantPrompt: "session[ep/-]> "},
		{name: "explicit session fails", inventory: protocol.CollectionSucceeded, explicit: protocol.CollectionFailed, wantError: "collection_status=failed"},
	}
	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			inventory := freshTestInventory()
			inventory.CollectionStatus = testCase.inventory
			inventory.Sessions[0].CollectionStatus = testCase.explicit
			stub := &freshnessStub{inventory: inventory}
			var output, errorsOut strings.Builder
			if err := RunInteractive(context.Background(), stub, strings.NewReader("cd ep/session-1\nquit\n"), &output, &errorsOut, InteractiveOptions{}); err != nil {
				t.Fatal(err)
			}
			if testCase.wantError != "" {
				if !strings.Contains(errorsOut.String(), testCase.wantError) {
					t.Fatalf("errors=%q want substring %q", errorsOut.String(), testCase.wantError)
				}
				return
			}
			if errorsOut.Len() != 0 || !strings.Contains(output.String(), testCase.wantPrompt) {
				t.Fatalf("navigation was not accepted: output=%q errors=%q", output.String(), errorsOut.String())
			}
		})
	}
}
