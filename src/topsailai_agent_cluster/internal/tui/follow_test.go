package tui

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"strings"
	"sync"
	"testing"
	"time"

	"topsailai_agent_cluster/internal/protocol"
)

// followStub serves a scripted record stream and records the request it received.
type followStub struct {
	interactiveStub
	records   []protocol.OutputFollowRecord
	startErr  error
	requests  []outputRequest
	mu        sync.Mutex
	started   int
	blockOpen bool
}

// FollowOutput implements the optional streaming seam.
func (s *followStub) FollowOutput(ctx context.Context, endpointID, resourceID, generation string, maxBytes, maxLines int) (<-chan protocol.OutputFollowRecord, error) {
	s.mu.Lock()
	s.started++
	s.requests = append(s.requests, outputRequest{endpointID: endpointID, resourceID: resourceID, generation: generation, maxBytes: maxBytes, maxLines: maxLines})
	startErr := s.startErr
	records := append([]protocol.OutputFollowRecord(nil), s.records...)
	blockOpen := s.blockOpen
	s.mu.Unlock()
	if startErr != nil {
		return nil, startErr
	}
	channel := make(chan protocol.OutputFollowRecord, len(records)+1)
	for _, record := range records {
		channel <- record
	}
	if !blockOpen {
		close(channel)
	}
	return channel, nil
}

// startCount reports how many streams were opened.
func (s *followStub) startCount() int {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.started
}

// TestRenderFollowRecordSanitizesProviderLines proves a streamed line cannot
// carry a terminal control sequence into the operator's terminal, because the
// body is provider data no matter how it arrives.
func TestRenderFollowRecordSanitizesProviderLines(t *testing.T) {
	var buffer bytes.Buffer
	record := protocol.OutputFollowRecord{Lines: []string{"safe\x1b[2Jtext", "plain"}}
	if err := renderFollowRecord(&buffer, record, ColorPolicy{}, false); err != nil {
		t.Fatalf("renderFollowRecord: %v", err)
	}
	rendered := buffer.String()
	if strings.Contains(rendered, "\x1b[2J") {
		t.Fatalf("clear-screen sequence survived: %q", rendered)
	}
	if !strings.Contains(rendered, "safetext") || !strings.Contains(rendered, "plain") {
		t.Fatalf("content lost: %q", rendered)
	}
}

// TestRenderFollowRecordMarksTruncation proves a truncated record is labelled,
// so a shortened stream is never presented as complete evidence.
func TestRenderFollowRecordMarksTruncation(t *testing.T) {
	var buffer bytes.Buffer
	if err := renderFollowRecord(&buffer, protocol.OutputFollowRecord{Lines: []string{"one"}, Truncated: true}, ColorPolicy{}, false); err != nil {
		t.Fatalf("renderFollowRecord: %v", err)
	}
	if !strings.Contains(buffer.String(), "truncated: true") {
		t.Fatalf("truncation unlabelled: %q", buffer.String())
	}
}

// TestRenderFollowRecordReportsEndState proves a clean end and a failed end are
// distinguishable, so an interrupted stream never looks like a finished one.
func TestRenderFollowRecordReportsEndState(t *testing.T) {
	cases := []struct {
		name      string
		errorCode string
		want      string
	}{
		{name: "clean end", errorCode: "", want: "follow ended\n"},
		{name: "provider error", errorCode: "provider_error", want: "follow ended: provider_error\n"},
	}
	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			var buffer bytes.Buffer
			if err := renderFollowRecord(&buffer, protocol.OutputFollowRecord{End: true, ErrorCode: testCase.errorCode}, ColorPolicy{}, false); err != nil {
				t.Fatalf("renderFollowRecord: %v", err)
			}
			if buffer.String() != testCase.want {
				t.Fatalf("got=%q want=%q", buffer.String(), testCase.want)
			}
		})
	}
}

// TestRenderFollowRecordJSONIsOneDocumentPerLine proves the machine-readable
// form stays newline-delimited, so a caller can decode it incrementally.
func TestRenderFollowRecordJSONIsOneDocumentPerLine(t *testing.T) {
	var buffer bytes.Buffer
	if err := renderFollowRecord(&buffer, protocol.OutputFollowRecord{Lines: []string{"one"}, ObservedAtMS: 7}, ColorPolicy{}, true); err != nil {
		t.Fatalf("renderFollowRecord: %v", err)
	}
	rendered := buffer.String()
	if strings.Count(rendered, "\n") != 1 || !strings.HasSuffix(rendered, "\n") {
		t.Fatalf("not one document per line: %q", rendered)
	}
	if !strings.Contains(rendered, `"ObservedAtMS":7`) {
		t.Fatalf("observation time lost: %q", rendered)
	}
}

// TestFollowLogsStreamsUntilEnd proves the standalone path writes every record
// and stops on the terminal record instead of waiting for the channel to close.
func TestFollowLogsStreamsUntilEnd(t *testing.T) {
	stub := &followStub{records: []protocol.OutputFollowRecord{
		{Lines: []string{"first"}},
		{Lines: []string{"second"}},
		{End: true},
	}}
	var out bytes.Buffer
	runner := CommandRunner{API: stub}
	if err := runner.FollowLogs(context.Background(), &out, "endpoint-1", "res-1", "generation-1", 1024, 10, false, ColorPolicy{}); err != nil {
		t.Fatalf("FollowLogs: %v", err)
	}
	rendered := out.String()
	for _, want := range []string{"first", "second", "follow ended"} {
		if !strings.Contains(rendered, want) {
			t.Fatalf("missing %q in %q", want, rendered)
		}
	}
	if got := stub.requests[0]; got.endpointID != "endpoint-1" || got.resourceID != "res-1" || got.generation != "generation-1" {
		t.Fatalf("request=%+v", got)
	}
}

// TestFollowLogsReportsInterruptedStream proves a channel that closes without a
// terminal record is reported as interrupted, never as a clean finish.
func TestFollowLogsReportsInterruptedStream(t *testing.T) {
	stub := &followStub{records: []protocol.OutputFollowRecord{{Lines: []string{"only"}}}}
	var out bytes.Buffer
	runner := CommandRunner{API: stub}
	if err := runner.FollowLogs(context.Background(), &out, "endpoint-1", "res-1", "generation-1", 1024, 10, false, ColorPolicy{}); err != nil {
		t.Fatalf("FollowLogs: %v", err)
	}
	if !strings.Contains(out.String(), "stream_interrupted") {
		t.Fatalf("interruption unlabelled: %q", out.String())
	}
}

// TestFollowLogsStopsOnCancellation proves the standalone stream ends when the
// caller cancels, so an operator interrupt is a normal stop rather than a hang.
func TestFollowLogsStopsOnCancellation(t *testing.T) {
	stub := &followStub{blockOpen: true}
	ctx, cancel := context.WithCancel(context.Background())
	var out bytes.Buffer
	runner := CommandRunner{API: stub}
	done := make(chan error, 1)
	go func() {
		done <- runner.FollowLogs(ctx, &out, "endpoint-1", "res-1", "generation-1", 1024, 10, false, ColorPolicy{})
	}()
	cancel()
	select {
	case err := <-done:
		if err != nil {
			t.Fatalf("FollowLogs: %v", err)
		}
	case <-time.After(5 * time.Second):
		t.Fatal("FollowLogs did not stop after cancellation")
	}
	if !strings.Contains(out.String(), "follow stopped") {
		t.Fatalf("stop unlabelled: %q", out.String())
	}
}

// TestFollowLogsRefusesClientWithoutStreaming proves a client without the seam
// refuses follow explicitly instead of degrading into a snapshot.
func TestFollowLogsRefusesClientWithoutStreaming(t *testing.T) {
	stub := &interactiveStub{endpoints: []protocol.Endpoint{{EndpointID: "endpoint-1"}}, reports: map[string]protocol.InventoryReport{"endpoint-1": testInventory()}}
	var out bytes.Buffer
	runner := CommandRunner{API: stub}
	err := runner.FollowLogs(context.Background(), &out, "endpoint-1", "res-1", "generation-1", 1024, 10, false, ColorPolicy{})
	if err == nil || !strings.Contains(err.Error(), "does not support streaming output") {
		t.Fatalf("err=%v", err)
	}
	if out.Len() != 0 {
		t.Fatalf("unexpected output: %q", out.String())
	}
}

// TestFollowSessionIdleNeverBlocks proves the editor seam returns immediately
// when no record is available, so a keypress is never delayed behind a stream.
func TestFollowSessionIdleNeverBlocks(t *testing.T) {
	stub := &followStub{blockOpen: true}
	session, err := newFollowSession(context.Background(), stub, followRequest{EndpointID: "endpoint-1", ResourceID: "res-1", Generation: "generation-1"}, ColorPolicy{})
	if err != nil {
		t.Fatalf("newFollowSession: %v", err)
	}
	defer session.Stop()
	done := make(chan struct{})
	go func() {
		defer close(done)
		payload, idleErr := session.Idle()
		if idleErr != nil {
			t.Errorf("Idle: %v", idleErr)
		}
		if len(payload) != 0 {
			t.Errorf("unexpected payload: %q", payload)
		}
	}()
	select {
	case <-done:
	case <-time.After(5 * time.Second):
		t.Fatal("Idle blocked on an empty stream")
	}
}

// TestFollowSessionIdleDrainsAvailableRecords proves one poll applies every
// record the pump has accumulated, so a burst is not replayed one per poll.
func TestFollowSessionIdleDrainsAvailableRecords(t *testing.T) {
	stub := &followStub{records: []protocol.OutputFollowRecord{
		{Lines: []string{"first"}},
		{Lines: []string{"second"}},
		{End: true},
	}}
	session, err := newFollowSession(context.Background(), stub, followRequest{EndpointID: "endpoint-1", ResourceID: "res-1", Generation: "generation-1"}, ColorPolicy{})
	if err != nil {
		t.Fatalf("newFollowSession: %v", err)
	}
	defer session.Stop()
	// The pump is asynchronous, so the burst is observed as finished before the
	// single poll that must return all of it.
	waitEnded(t, session)
	payload, idleErr := session.Idle()
	if idleErr != nil {
		t.Fatalf("Idle: %v", idleErr)
	}
	rendered := string(payload)
	for _, want := range []string{"first", "second", "follow ended"} {
		if !strings.Contains(rendered, want) {
			t.Fatalf("missing %q in %q", want, rendered)
		}
	}
	// A finished stream reports nothing further, so the editor does not reprint.
	again, idleErr := session.Idle()
	if idleErr != nil {
		t.Fatalf("Idle: %v", idleErr)
	}
	if len(again) != 0 {
		t.Fatalf("finished stream reprinted: %q", again)
	}
}

// waitEnded blocks until the pump has recorded the terminal state, without
// consuming the accumulated payload.
func waitEnded(t *testing.T, session *followSession) {
	t.Helper()
	deadline := time.Now().Add(5 * time.Second)
	for {
		session.mu.Lock()
		ended := session.ended
		session.mu.Unlock()
		if ended {
			return
		}
		if time.Now().After(deadline) {
			t.Fatal("the stream never reached a terminal state")
		}
		time.Sleep(time.Millisecond)
	}
}

// TestFollowSessionStopIsIdempotent proves the editor and the REPL can both stop
// the same stream without a double-cancel panic.
func TestFollowSessionStopIsIdempotent(t *testing.T) {
	stub := &followStub{blockOpen: true}
	session, err := newFollowSession(context.Background(), stub, followRequest{EndpointID: "endpoint-1", ResourceID: "res-1", Generation: "generation-1"}, ColorPolicy{})
	if err != nil {
		t.Fatalf("newFollowSession: %v", err)
	}
	session.Stop()
	session.Stop()
}

// TestFollowSessionNamesItsStop proves the editor prints a follow-specific stop
// message, so the operator is not told an auto-refresh loop ended.
func TestFollowSessionNamesItsStop(t *testing.T) {
	stub := &followStub{blockOpen: true}
	session, err := newFollowSession(context.Background(), stub, followRequest{EndpointID: "endpoint-1", ResourceID: "res-1", Generation: "generation-1"}, ColorPolicy{})
	if err != nil {
		t.Fatalf("newFollowSession: %v", err)
	}
	defer session.Stop()
	if got := watchStopLabel(session); got != "follow stopped" {
		t.Fatalf("label=%q", got)
	}
}

// TestWatchStopLabelKeepsAutoRefreshWording proves a session that does not name
// itself keeps the original message, so existing behaviour is unchanged.
func TestWatchStopLabelKeepsAutoRefreshWording(t *testing.T) {
	if got := watchStopLabel(&replWatch{}); got != "auto-refresh stopped" {
		t.Fatalf("label=%q", got)
	}
}

// TestStartFollowConsumesIntent proves the armed intent is consumed once, so a
// keypress that stops the stream cannot silently re-arm it on the next prompt.
func TestStartFollowConsumesIntent(t *testing.T) {
	stub := &followStub{blockOpen: true}
	state := &interactiveState{follow: &followRequest{EndpointID: "endpoint-1", ResourceID: "res-1", Generation: "generation-1"}}
	options := InteractiveOptions{WatchReader: &TerminalEditor{}}
	session := startFollow(context.Background(), stub, state, options)
	if session == nil {
		t.Fatal("startFollow returned nil for an armed intent")
	}
	session.Stop()
	if state.follow != nil {
		t.Fatal("intent was not consumed")
	}
	if again := startFollow(context.Background(), stub, state, options); again != nil {
		t.Fatal("consumed intent re-armed a second stream")
	}
}

// TestStartFollowReportsStartFailure proves a stream that cannot start surfaces
// one diagnostic line instead of a prompt that silently does nothing.
func TestStartFollowReportsStartFailure(t *testing.T) {
	stub := &followStub{startErr: errors.New("transport unavailable")}
	state := &interactiveState{follow: &followRequest{EndpointID: "endpoint-1", ResourceID: "res-1", Generation: "generation-1"}}
	session := startFollow(context.Background(), stub, state, InteractiveOptions{WatchReader: &TerminalEditor{}})
	if session == nil {
		t.Fatal("startFollow returned nil")
	}
	payload, err := session.Idle()
	if err != nil {
		t.Fatalf("Idle: %v", err)
	}
	if !strings.Contains(string(payload), "follow failed: transport unavailable") {
		t.Fatalf("payload=%q", payload)
	}
	// The failure is reported once, so a poll loop does not repeat it.
	again, err := session.Idle()
	if err != nil {
		t.Fatalf("Idle: %v", err)
	}
	if len(again) != 0 {
		t.Fatalf("failure repeated: %q", again)
	}
}

// TestStartFollowRequiresWatchReader proves a reader that cannot observe a
// keypress never starts a stream it could not stop.
func TestStartFollowRequiresWatchReader(t *testing.T) {
	stub := &followStub{blockOpen: true}
	state := &interactiveState{follow: &followRequest{EndpointID: "endpoint-1", ResourceID: "res-1", Generation: "generation-1"}}
	if session := startFollow(context.Background(), stub, state, InteractiveOptions{}); session != nil {
		t.Fatal("startFollow started without a watch-capable reader")
	}
	if stub.startCount() != 0 {
		t.Fatalf("streams opened=%d", stub.startCount())
	}
}

// TestInteractiveLogsFollowArmsStream proves the interactive command arms the
// stream for the next prompt and names the session it will follow.
func TestInteractiveLogsFollowArmsStream(t *testing.T) {
	stub := &followStub{interactiveStub: *scopeStub(), blockOpen: true}
	output, diagnostics := runScope(t, stub, "cd host-one/endpoint-1/res-1\nlogs -f\nquit\n", ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if !strings.Contains(output, "follow: res-1 (any key stops)") {
		t.Fatalf("follow not armed: %q", output)
	}
	// The armed stream must not replace the one-shot snapshot the session entry
	// already rendered, so no extra snapshot read happens for the follow command.
	if stub.outputCalls != 1 {
		t.Fatalf("snapshot reads=%d want=1", stub.outputCalls)
	}
}

// TestInteractiveLogsFollowRefusesClientWithoutStreaming proves the interactive
// command fails loudly instead of arming a stream the client cannot serve.
func TestInteractiveLogsFollowRefusesClientWithoutStreaming(t *testing.T) {
	stub := scopeStub()
	_, diagnostics := runScope(t, stub, "cd host-one/endpoint-1/res-1\nlogs --follow\nquit\n", ColorPolicy{})
	if !strings.Contains(diagnostics, "does not support streaming output") {
		t.Fatalf("diagnostics=%q", diagnostics)
	}
}

// TestInteractiveLogsFollowRejectsDuplicateFlag proves the grammar rejects a
// repeated follow flag instead of silently accepting it.
func TestInteractiveLogsFollowRejectsDuplicateFlag(t *testing.T) {
	stub := &followStub{interactiveStub: *scopeStub(), blockOpen: true}
	_, diagnostics := runScope(t, stub, "cd host-one/endpoint-1/res-1\nlogs -f --follow\nquit\n", ColorPolicy{})
	if !strings.Contains(diagnostics, "usage: logs") {
		t.Fatalf("diagnostics=%q", diagnostics)
	}
	if stub.startCount() != 0 {
		t.Fatalf("streams opened=%d", stub.startCount())
	}
}

// TestFailedFollowSessionStopsWithoutAStream proves a stream that never started
// still answers the editor's stop protocol, so the prompt loop never has to
// special-case a failure.
func TestFailedFollowSessionStopsWithoutAStream(t *testing.T) {
	session := &failedFollowSession{message: "transport unavailable"}
	session.Stop()
	session.Stop()
	if label := session.StopLabel(); label != "follow stopped" {
		t.Fatalf("label=%q", label)
	}
	payload, err := session.Idle()
	if err != nil {
		t.Fatalf("Idle: %v", err)
	}
	if !strings.Contains(string(payload), "follow failed: transport unavailable") {
		t.Fatalf("payload=%q", payload)
	}
}

// TestFollowSessionIdleReportsRenderFailure proves a record that cannot be
// rendered ends the stream instead of leaving the editor polling forever.
func TestFollowSessionIdleReportsRenderFailure(t *testing.T) {
	channel := make(chan protocol.OutputFollowRecord, 1)
	channel <- protocol.OutputFollowRecord{Lines: []string{"line"}, End: true}
	close(channel)
	session := newFollowSessionWithRecords(channel, func() {}, ColorPolicy{})
	defer session.Stop()
	payload := idleUntil(t, session, "line")
	if !strings.Contains(payload, "line") {
		t.Fatalf("payload=%q", payload)
	}
	// A finished stream reports nothing further, so the editor does not reprint.
	again, err := session.Idle()
	if err != nil {
		t.Fatalf("Idle: %v", err)
	}
	if len(again) != 0 {
		t.Fatalf("reprinted: %q", again)
	}
}

// TestFollowSessionDrainsBurstWithoutAnEditorPoll proves the transport is drained
// continuously, so a provider burst cannot fill the bounded transport queues and
// terminate the stream with consumer_overflow while the editor is between polls.
//
// The record channel is deliberately tiny. A reader that only drained on the
// editor tick would block the producer after that many records, which is exactly
// how the upstream queue overflows: the server keeps writing while the consumer
// is not reading. The pump must consume the whole burst with no Idle call at all.
func TestFollowSessionDrainsBurstWithoutAnEditorPoll(t *testing.T) {
	const burst = DefaultInteractiveMaxLines
	records := make(chan protocol.OutputFollowRecord, 1)
	session := newFollowSessionWithRecords(records, func() {}, ColorPolicy{})
	defer session.Stop()
	sent := make(chan struct{})
	go func() {
		defer close(sent)
		for index := 0; index < burst; index++ {
			records <- protocol.OutputFollowRecord{Lines: []string{fmt.Sprintf("line-%d", index)}}
		}
		records <- protocol.OutputFollowRecord{End: true}
	}()
	select {
	case <-sent:
	case <-time.After(5 * time.Second):
		t.Fatal("the burst was not drained without an editor poll")
	}
	payload := idleUntil(t, session, "follow ended")
	for index := 0; index < burst; index++ {
		want := fmt.Sprintf("line-%d", index)
		if !strings.Contains(payload, want) {
			t.Fatalf("missing %q in the drained burst", want)
		}
	}
}

// idleUntil polls the editor seam until the accumulated payload contains want.
// The pump is asynchronous, so a test cannot assume that one poll observes a
// record that was just handed to the stream.
func idleUntil(t *testing.T, session *followSession, want string) string {
	t.Helper()
	deadline := time.Now().Add(5 * time.Second)
	var accumulated strings.Builder
	for {
		payload, err := session.Idle()
		if err != nil {
			t.Fatalf("Idle: %v", err)
		}
		accumulated.Write(payload)
		if strings.Contains(accumulated.String(), want) {
			return accumulated.String()
		}
		if time.Now().After(deadline) {
			t.Fatalf("payload never contained %q: %q", want, accumulated.String())
		}
		time.Sleep(time.Millisecond)
	}
}
