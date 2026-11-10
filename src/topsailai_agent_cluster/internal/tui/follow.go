package tui

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"sync"

	"topsailai_agent_cluster/internal/protocol"
)

// followRequest is the parsed intent of one follow command. It carries the
// generation resolved from the committed inventory, so the stream is bound to
// the exact session the operator selected rather than to whatever the provider
// reports later.
type followRequest struct {
	EndpointID         string
	ResourceID         string
	ProviderGeneration string
	MaxBytes           int
	MaxLines           int
}

// OutputFollower is the optional streaming seam. A client without it keeps the
// one-shot snapshot behaviour and refuses follow explicitly, so an operator is
// never shown a snapshot that silently pretends to be a stream.
type OutputFollower interface {
	FollowOutput(ctx context.Context, endpointID, resourceID, generation string, maxBytes, maxLines int) (<-chan protocol.OutputFollowRecord, error)
}

// followStopLabel is the message printed when a keypress ends a stream. A
// session that does not implement it keeps the auto-refresh wording, so the
// existing watch behaviour stays byte-identical.
type followStopLabel interface {
	StopLabel() string
}

// followStatusPrefix names the writer of every follow status line, so a status
// line is never mistaken for provider output that happens to contain the same
// words. It is rendered as a named prompt, so it carries the same bold-green
// wrapper as the REPL prompt and the terminal editor's column accounting stays
// identical to the plain form.
const followStatusPrefix = "log.follow>"

// renderFollowStatus returns one follow status line. The prefix is always
// present, because the operator asked for a way to tell these lines apart from
// agent output; the message style carries the severity, so a clean end and an
// error are distinguishable at a glance. With colour disabled the plain
// "log.follow> <message>" form is returned, so a redirected stream and a
// --no-color run stay readable and byte-stable.
//
// jsonMode returns the bare message, because a JSON consumer parses records and a
// prefix or an escape sequence would corrupt the stream it is reading.
func renderFollowStatus(message, style string, policy ColorPolicy, jsonMode bool) string {
	if jsonMode {
		return message
	}
	prefix := RenderNamedPrompt(followStatusPrefix, policy)
	if !policy.Enabled || style == "" {
		return prefix + message
	}
	return prefix + style + message + ansiReset
}

// renderFollowRecord appends one streamed record to the buffer. The body is
// provider data, so every line is sanitized through the same boundary the
// snapshot renderer uses; a stream must never be able to move the cursor or
// retitle the window just because it arrives in pieces.
func renderFollowRecord(buffer *bytes.Buffer, record protocol.OutputFollowRecord, color ColorPolicy, jsonMode bool) error {
	if err := renderFollowBody(buffer, record, color, jsonMode); err != nil {
		return err
	}
	renderFollowTerminal(buffer, record, color, jsonMode)
	return nil
}

// renderFollowBody appends only the provider data of one record, so a caller can
// measure how much provider output a record carries without counting the status
// line that follows it. A status line is this service's own message, never
// evidence that the operator saw provider output.
func renderFollowBody(buffer *bytes.Buffer, record protocol.OutputFollowRecord, color ColorPolicy, jsonMode bool) error {
	if jsonMode {
		encoded, err := json.Marshal(record)
		if err != nil {
			return fmt.Errorf("encode follow record: %w", err)
		}
		buffer.Write(encoded)
		buffer.WriteByte('\n')
		return nil
	}
	for _, line := range record.Lines {
		buffer.WriteString(filterProviderOutput(line, color))
		buffer.WriteByte('\n')
	}
	if record.Truncated {
		buffer.WriteString("truncated: true\n")
	}
	return nil
}

// renderFollowTerminal appends the status line of a terminal record. A record
// that is not terminal contributes nothing, so the two halves compose into the
// same bytes renderFollowRecord always produced.
func renderFollowTerminal(buffer *bytes.Buffer, record protocol.OutputFollowRecord, color ColorPolicy, jsonMode bool) {
	if !record.End {
		return
	}
	if record.ErrorCode == "" {
		// A clean end needs no attention, so the message is dim.
		buffer.WriteString(renderFollowStatus("follow ended", ansiDim, color, jsonMode))
		buffer.WriteByte('\n')
		return
	}
	// An error code needs a look, so the message is red.
	buffer.WriteString(renderFollowStatus("follow ended: "+sanitizeInlineText(record.ErrorCode), ansiRed, color, jsonMode))
	buffer.WriteByte('\n')
}

// FollowLogs streams output records until the stream ends or ctx is cancelled.
// It is the standalone path: there is no terminal to observe a keypress, so the
// caller owns cancellation. A cancelled stream is a normal stop, not a failure,
// because the operator asked to stop watching rather than reporting an error.
func (r CommandRunner) FollowLogs(ctx context.Context, out io.Writer, endpointID, resourceID, generation string, maxBytes, maxLines int, jsonMode bool, color ColorPolicy) error {
	follower, ok := r.API.(OutputFollower)
	if !ok {
		return fmt.Errorf("follow is unavailable: the API client does not support streaming output")
	}
	records, err := follower.FollowOutput(ctx, endpointID, resourceID, generation, maxBytes, maxLines)
	if err != nil {
		return err
	}
	for {
		select {
		case <-ctx.Done():
			// An operator stop is a normal end, so the message is dim.
			_, writeErr := fmt.Fprintln(out, renderFollowStatus("follow stopped", ansiDim, color, jsonMode))
			return writeErr
		case record, open := <-records:
			if !open {
				// A channel that closes without an end record is an interrupted
				// stream, never a clean finish, so the message is red.
				_, writeErr := fmt.Fprintln(out, renderFollowStatus("follow ended: stream_interrupted", ansiRed, color, jsonMode))
				return writeErr
			}
			var buffer bytes.Buffer
			if err := renderFollowRecord(&buffer, record, color, jsonMode); err != nil {
				return err
			}
			if _, err := out.Write(buffer.Bytes()); err != nil {
				return err
			}
			if record.End {
				return nil
			}
		}
	}
}

// followPendingBytes bounds the rendered output that may wait for the editor to
// print it. The pump keeps reading the stream while the editor is between polls,
// so a provider burst is absorbed here instead of overflowing the transport
// queue. The bound is deliberately larger than one requested tail, because the
// default REPL tail is 300 lines and a burst of that size must never be reported
// as a consumer overflow.
const followPendingBytes = 4 << 20

// followSession streams provider output while the editor waits for a key. It
// implements WatchSession, so the existing editor loop observes it between
// polls and stops it on the first decoded key without a second goroutine
// writing to the terminal.
//
// A pump goroutine is the only reader of the record stream. It renders each
// record as it arrives and holds the bytes until the editor prints them, so the
// transport is drained continuously instead of once per editor poll. Draining
// only on the poll tick let a provider burst fill the bounded transport queues
// and terminate the stream with consumer_overflow, even though the operator's
// terminal was keeping up.
type followSession struct {
	records <-chan protocol.OutputFollowRecord
	cancel  context.CancelFunc
	color   ColorPolicy
	done    chan struct{}
	// request is the intent this stream was opened for, so a recovery snapshot
	// addresses the session that was followed rather than whatever the selection
	// happens to be when the stream ends.
	request followRequest

	mu      sync.Mutex
	cond    *sync.Cond
	pending []byte
	ended   bool
	err     error

	// providerPending counts provider bytes queued but not yet handed to the
	// terminal, and providerPrinted records that at least one such byte was
	// handed over. The distinction is load-bearing: a keypress that arrives
	// before the editor's idle tick ends the read with the bytes still pending,
	// so the operator saw nothing even though records were received.
	providerPending int
	providerPrinted bool
	// terminalSeen and terminalCode describe the stream's own terminal record.
	// A stream that ends without one was interrupted, never finished.
	terminalSeen bool
	terminalCode string
	interrupted  bool
	// stoppedLive records that the operator stopped a stream that had not yet
	// ended on its own. It is what distinguishes a keypress from a reported end,
	// so a keypress that discarded unprinted bytes can still be recovered.
	stoppedLive bool

	stopOnce sync.Once
}

// newFollowSession starts one stream. The caller owns the parent context, so a
// prompt that ends for any reason also ends the stream.
func newFollowSession(parent context.Context, api InteractiveAPI, request followRequest, color ColorPolicy) (*followSession, error) {
	follower, ok := api.(OutputFollower)
	if !ok {
		return nil, fmt.Errorf("follow is unavailable: the API client does not support streaming output")
	}
	ctx, cancel := context.WithCancel(parent)
	records, err := follower.FollowOutput(ctx, request.EndpointID, request.ResourceID, request.ProviderGeneration, request.MaxBytes, request.MaxLines)
	if err != nil {
		cancel()
		return nil, err
	}
	return newFollowSessionWithRecords(records, cancel, color, request), nil
}

// newFollowSessionWithRecords starts the pump for an already opened stream. It is
// the single construction path, so a session can never exist without a reader
// that drains the transport between editor polls. The request is carried so a
// recovery snapshot can address the session that was followed.
func newFollowSessionWithRecords(records <-chan protocol.OutputFollowRecord, cancel context.CancelFunc, color ColorPolicy, request followRequest) *followSession {
	session := &followSession{records: records, cancel: cancel, color: color, done: make(chan struct{}), request: request}
	session.cond = sync.NewCond(&session.mu)
	go session.pump()
	return session
}

// pump is the only reader of the record stream. It renders every record as it
// arrives, so the transport never waits for the editor's poll tick.
//
// Provider bytes and the terminal status line are counted separately, because
// only provider bytes prove the operator saw output. A stream that ends with
// nothing but its own status line showed the operator no output at all.
func (s *followSession) pump() {
	for {
		select {
		case <-s.done:
			return
		case record, open := <-s.records:
			if !open {
				// A channel that closes without a terminal record is an
				// interrupted stream, never a clean finish, so the message is red.
				s.markInterrupted()
				s.finish([]byte(renderFollowStatus("follow ended: stream_interrupted", ansiRed, s.color, false)+"\n"), nil)
				return
			}
			var body, terminal bytes.Buffer
			if err := renderFollowBody(&body, record, s.color, false); err != nil {
				s.finish(nil, err)
				return
			}
			renderFollowTerminal(&terminal, record, s.color, false)
			if record.End {
				s.markTerminal(record.ErrorCode)
			}
			if !s.append(body.Bytes(), terminal.Bytes(), len(body.Bytes()), record.End) {
				return
			}
			if record.End {
				return
			}
		}
	}
}

// append holds one rendered record until the editor prints it. It reports false
// when the stream was stopped, so the pump exits instead of accumulating output
// nobody will read.
//
// The pending bound applies backpressure rather than dropping data: a consumer
// that genuinely cannot keep up must be reported as an overflow by the transport,
// never silently presented with a partial stream. A single record larger than the
// bound is still accepted once the buffer is empty, because waiting for room that
// can never be freed would deadlock the pump.
//
// providerBytes counts only the provider data of this record, so the printed
// evidence never includes this service's own status line.
func (s *followSession) append(body, terminal []byte, providerBytes int, end bool) bool {
	s.mu.Lock()
	defer s.mu.Unlock()
	payload := len(body) + len(terminal)
	for !s.ended && len(s.pending) > 0 && len(s.pending)+payload > followPendingBytes {
		s.cond.Wait()
	}
	if s.ended {
		return false
	}
	s.pending = append(s.pending, body...)
	s.pending = append(s.pending, terminal...)
	s.providerPending += providerBytes
	if end {
		s.ended = true
	}
	return true
}

// markTerminal records the stream's own terminal record, so a later recovery
// decision can tell a reported end from an interruption.
func (s *followSession) markTerminal(code string) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.terminalSeen = true
	s.terminalCode = code
}

// markInterrupted records that the stream ended without a terminal record. The
// client reports that case as stream_interrupted, so the recovery decision must
// treat it as an abnormal end rather than a clean finish.
func (s *followSession) markInterrupted() {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.interrupted = true
}

// finish records the terminal state of the stream and wakes any waiter.
func (s *followSession) finish(payload []byte, err error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.ended {
		return
	}
	s.pending = append(s.pending, payload...)
	s.err = err
	s.ended = true
	s.cond.Broadcast()
}

// Idle returns every byte the pump has accumulated and clears them. It never
// blocks, so a keypress is never delayed behind a slow stream.
//
// Returning the bytes is the moment they reach the terminal, so this is where
// pending provider bytes become printed evidence. Counting at the receive
// boundary instead would claim the operator saw output that a fast keypress
// discarded before the editor ever printed it.
func (s *followSession) Idle() ([]byte, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	payload := s.pending
	s.pending = nil
	err := s.err
	s.err = nil
	if len(payload) > 0 {
		if s.providerPending > 0 {
			s.providerPrinted = true
		}
		s.providerPending = 0
		// The pump may be waiting for room, so releasing the buffer must wake it.
		s.cond.Signal()
	}
	return emptyToNil(payload), err
}

// emptyToNil reports no payload when nothing was accumulated, so the editor
// does not reprint an empty block on every poll.
func emptyToNil(payload []byte) []byte {
	if len(payload) == 0 {
		return nil
	}
	return payload
}

// Stop ends the stream. It is idempotent, because the editor stops the session
// on a keypress and the REPL stops it again when the prompt returns.
//
// The session is marked ended and the pump is released before the context is
// cancelled, so a pump waiting for room in the pending buffer, or waiting on a
// record that will never arrive, exits instead of holding the goroutine after
// the operator stopped watching.
//
// A stop that arrives while the stream is still live is recorded separately,
// because that is the operator's keypress. The distinction matters: a keypress
// discards the bytes still pending, so the operator can stop a stream that had
// already received records and still see nothing.
func (s *followSession) Stop() {
	s.stopOnce.Do(func() {
		s.mu.Lock()
		if !s.terminalSeen && !s.interrupted {
			s.stoppedLive = true
		}
		s.ended = true
		s.cond.Broadcast()
		s.mu.Unlock()
		close(s.done)
		s.cancel()
	})
}

// StopLabel names this session in the editor's stop message, so the operator
// reads the follow wording rather than the auto-refresh wording. It returns the
// bare message, because the editor owns the writer and therefore owns the
// prefix and the colour policy; rendering here would need a policy this seam
// does not receive.
func (s *followSession) StopLabel() string { return "follow stopped" }

// Ended reports that the stream ended on its own rather than being stopped by
// the operator. The editor uses it to avoid printing a stop message for a stream
// that had already reported its own end, which would otherwise read as a second,
// contradictory event.
func (s *followSession) Ended() bool {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.terminalSeen || s.interrupted
}

// Recovery reports whether the operator was left without output and, if so, what
// to read instead. It returns the intent that was followed, so the snapshot
// addresses the session the operator asked to watch rather than whatever the
// selection happens to be when the stream ends.
//
// Two independent triggers recover, because they cover different failures:
//
//   - An abnormal end always recovers, even when records were printed. A stream
//     that broke after 63 of 300 records showed the operator a partial tail, and
//     the snapshot is the only way to see the rest. It recovers whether or not
//     the operator typed a command afterwards, because the stream failed rather
//     than being dismissed.
//   - A keypress that stopped a live stream before anything was printed recovers
//     only when the operator did not type a command. The editor prints on its
//     idle tick, so a fast or repeated keypress ends the read with the bytes
//     still pending and the operator sees an empty screen even though records
//     were received. A real command means the operator deliberately moved on, so
//     restoring the tail would answer a question they stopped asking.
//
// A clean end with nothing printed does not recover, because the provider had
// nothing to show: the snapshot would be empty too, and printing it would only
// add noise. endpoint_offline does not recover either, because the snapshot
// travels the same channel and would fail identically.
func (s *followSession) Recovery(operatorContinued bool) (followRequest, string, bool) {
	s.mu.Lock()
	defer s.mu.Unlock()
	code := s.terminalCode
	if s.interrupted {
		code = "stream_interrupted"
	}
	if code == "endpoint_offline" {
		return followRequest{}, "", false
	}
	if code != "" || s.interrupted {
		return s.request, code, true
	}
	if s.stoppedLive && !s.providerPrinted && !operatorContinued {
		return s.request, "no_output", true
	}
	return followRequest{}, "", false
}

// startFollow activates an armed follow intent for the next prompt. It consumes
// the intent, so a keypress that stops the stream cannot silently re-arm it on
// the following prompt.
func startFollow(parent context.Context, api InteractiveAPI, state *interactiveState, options InteractiveOptions) WatchSession {
	if state.follow == nil {
		return nil
	}
	request := *state.follow
	state.follow = nil
	if options.WatchReader == nil {
		return nil
	}
	session, err := newFollowSession(parent, api, request, options.Color)
	if err != nil {
		// The stream could not start, so the operator gets one diagnostic line
		// instead of a prompt that silently does nothing.
		return &failedFollowSession{message: err.Error(), color: options.Color}
	}
	return session
}

// failedFollowSession reports a stream that never started. It exists so the
// failure surfaces on the next prompt through the same seam, instead of being
// swallowed by the command that armed the intent. It carries the colour policy
// because it renders its own line, and a failure is red rather than dim.
type failedFollowSession struct {
	message string
	color   ColorPolicy
	once    sync.Once
}

// Idle reports the start failure exactly once.
func (s *failedFollowSession) Idle() ([]byte, error) {
	var payload []byte
	s.once.Do(func() {
		payload = []byte(renderFollowStatus("follow failed: "+sanitizeInlineText(s.message), ansiRed, s.color, false) + "\n")
	})
	return payload, nil
}

// Stop is a no-op, because no stream was started.
func (s *failedFollowSession) Stop() {}

// StopLabel names this session in the editor's stop message.
func (s *failedFollowSession) StopLabel() string { return "follow stopped" }
