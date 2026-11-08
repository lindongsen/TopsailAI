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
	EndpointID string
	ResourceID string
	Generation string
	MaxBytes   int
	MaxLines   int
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

// renderFollowRecord appends one streamed record to the buffer. The body is
// provider data, so every line is sanitized through the same boundary the
// snapshot renderer uses; a stream must never be able to move the cursor or
// retitle the window just because it arrives in pieces.
func renderFollowRecord(buffer *bytes.Buffer, record protocol.OutputFollowRecord, color ColorPolicy, jsonMode bool) error {
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
	if !record.End {
		return nil
	}
	if record.ErrorCode == "" {
		buffer.WriteString("follow ended\n")
		return nil
	}
	buffer.WriteString("follow ended: " + sanitizeInlineText(record.ErrorCode) + "\n")
	return nil
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
			_, writeErr := fmt.Fprintln(out, "follow stopped")
			return writeErr
		case record, open := <-records:
			if !open {
				// A channel that closes without an end record is an interrupted
				// stream, never a clean finish.
				_, writeErr := fmt.Fprintln(out, "follow ended: stream_interrupted")
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

// followSession streams provider output while the editor waits for a key. It
// implements WatchSession, so the existing editor loop observes it between
// polls and stops it on the first decoded key without a second goroutine
// writing to the terminal.
type followSession struct {
	records <-chan protocol.OutputFollowRecord
	cancel  context.CancelFunc
	color   ColorPolicy

	mu    sync.Mutex
	ended bool

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
	records, err := follower.FollowOutput(ctx, request.EndpointID, request.ResourceID, request.Generation, request.MaxBytes, request.MaxLines)
	if err != nil {
		cancel()
		return nil, err
	}
	return &followSession{records: records, cancel: cancel, color: color}, nil
}

// Idle drains every record that is already available and returns the bytes to
// print. It never blocks, so a keypress is never delayed behind a slow stream.
func (s *followSession) Idle() ([]byte, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.ended {
		return nil, nil
	}
	var buffer bytes.Buffer
	for {
		select {
		case record, open := <-s.records:
			if !open {
				s.ended = true
				buffer.WriteString("follow ended: stream_interrupted\n")
				return emptyToNil(buffer.Bytes()), nil
			}
			if err := renderFollowRecord(&buffer, record, s.color, false); err != nil {
				s.ended = true
				return emptyToNil(buffer.Bytes()), err
			}
			if record.End {
				s.ended = true
				return emptyToNil(buffer.Bytes()), nil
			}
		default:
			return emptyToNil(buffer.Bytes()), nil
		}
	}
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
func (s *followSession) Stop() {
	s.stopOnce.Do(s.cancel)
}

// StopLabel names this session in the editor's stop message, so the operator
// reads "follow stopped" rather than the auto-refresh wording.
func (s *followSession) StopLabel() string { return "follow stopped" }

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
		return &failedFollowSession{message: err.Error()}
	}
	return session
}

// failedFollowSession reports a stream that never started. It exists so the
// failure surfaces on the next prompt through the same seam, instead of being
// swallowed by the command that armed the intent.
type failedFollowSession struct {
	message string
	once    sync.Once
}

// Idle reports the start failure exactly once.
func (s *failedFollowSession) Idle() ([]byte, error) {
	var payload []byte
	s.once.Do(func() {
		payload = []byte("follow failed: " + sanitizeInlineText(s.message) + "\n")
	})
	return payload, nil
}

// Stop is a no-op, because no stream was started.
func (s *failedFollowSession) Stop() {}

// StopLabel names this session in the editor's stop message.
func (s *failedFollowSession) StopLabel() string { return "follow stopped" }
