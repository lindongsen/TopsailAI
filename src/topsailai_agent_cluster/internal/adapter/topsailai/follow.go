package topsailai

import (
	"bufio"
	"context"
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"strings"
	"time"

	"topsailai_agent_cluster/internal/adapter"
)

// followDefaultRecordBytes is the per-record byte budget used when a caller does
// not request one. It matches the Server default so an unspecified budget behaves
// the same on both sides of the channel.
const followDefaultRecordBytes = 64 << 10

// followMaxRecordBytes is the absolute per-record ceiling. It matches the Server
// clamp: a larger request is reduced here rather than silently honoured, because
// one provider record must never be able to exhaust Endpoint memory.
const followMaxRecordBytes = 1 << 20

// followWaitDelay bounds how long Wait blocks after cancellation, so a
// grandchild that inherited the pipe cannot keep the Endpoint waiting forever.
const followWaitDelay = 5 * time.Second

// followRecord is one followed provider record. Truncated reports that the
// provider wrote more than the byte budget, so the consumer knows the record is
// shortened instead of complete.
type followRecord struct {
	Line      string
	Truncated bool
}

// followRunner streams provider output records as they are written.
type followRunner interface {
	Follow(context.Context, string, []string, int, func(followRecord) error) error
}

// execFollowRunner runs one provider follow command and delivers complete lines.
type execFollowRunner struct {
	timeout time.Duration
}

// Follow starts the provider follow command and calls emit once per complete
// record, truncating any record longer than limit bytes.
//
// The child environment sets PYTHONUNBUFFERED so records arrive as they are
// written. Without it the provider buffers stdout when it is not attached to a
// terminal, so a follow would deliver nothing until the process exited and the
// operator would see an empty screen instead of a live stream. The provider CLI
// is launched through "uv run", which does not add the variable itself.
//
// The provider rejects --json together with --follow, so the caller passes plain
// text arguments and this runner never parses a document.
func (r execFollowRunner) Follow(parent context.Context, executable string, args []string, limit int, emit func(followRecord) error) error {
	timeout := r.timeout
	if timeout <= 0 {
		timeout = defaultTimeout
	}
	ctx, cancel := context.WithTimeout(parent, timeout)
	defer cancel()
	cmd := exec.CommandContext(ctx, executable, args...)
	cmd.Env = followEnvironment(executable, os.Environ())
	configureProcessGroup(cmd)
	cmd.Cancel = func() error { return killProcessGroup(cmd) }
	cmd.WaitDelay = followWaitDelay
	stdout, err := cmd.StdoutPipe()
	if err != nil {
		return fmt.Errorf("prepare follow stdout: %w", err)
	}
	if err := cmd.Start(); err != nil {
		return fmt.Errorf("start follow command: %w", err)
	}
	readErr := scanFollowLines(stdout, limit, emit)
	if readErr != nil && !errors.Is(readErr, adapter.ErrFollowStopped) {
		// A consumer that stopped on purpose still needs the child reaped, so
		// termination is requested and the wait below still runs.
		_ = killProcessGroup(cmd)
	}
	waitErr := cmd.Wait()
	if readErr != nil {
		return readErr
	}
	if waitErr != nil {
		if ctx.Err() != nil {
			return ctx.Err()
		}
		return fmt.Errorf("follow command failed: %w", waitErr)
	}
	return nil
}

// scanFollowLines delivers complete newline-terminated records and holds the
// unterminated remainder until the stream ends, so a consumer never receives a
// partial line as if it were complete.
//
// A record longer than limit is truncated on a UTF-8 boundary and labelled, and
// the rest of that record is discarded up to the next newline. The stream then
// continues. Ending the stream instead would report a provider failure for what
// is only an oversized record, and the operator would lose every later record
// because one line was long.
func scanFollowLines(reader io.Reader, limit int, emit func(followRecord) error) error {
	if limit <= 0 {
		limit = followDefaultRecordBytes
	}
	if limit > followMaxRecordBytes {
		limit = followMaxRecordBytes
	}
	buffered := bufio.NewReaderSize(reader, 64<<10)
	for {
		record, ok, err := readFollowRecord(buffered, limit)
		if ok {
			if emitErr := emit(record); emitErr != nil {
				return emitErr
			}
		}
		if err != nil {
			if errors.Is(err, io.EOF) {
				return nil
			}
			return fmt.Errorf("read follow output: %w", err)
		}
	}
}

// readFollowRecord reads one record, bounded by limit bytes. It reports ok=false
// only when the stream ended with no remaining bytes, so a blank line is still a
// record and a trailing unterminated record is still delivered.
func readFollowRecord(reader *bufio.Reader, limit int) (followRecord, bool, error) {
	var record followRecord
	var collected []byte
	discarding := false
	for {
		piece, err := reader.ReadSlice('\n')
		if len(piece) > 0 {
			terminated := piece[len(piece)-1] == '\n'
			if terminated {
				piece = piece[:len(piece)-1]
			}
			if !discarding {
				room := limit - len(collected)
				if len(piece) <= room {
					collected = append(collected, piece...)
				} else {
					collected = append(collected, truncateUTF8(piece, room)...)
					record.Truncated = true
					discarding = true
				}
			}
			if terminated {
				record.Line = string(collected)
				return record, true, nil
			}
		}
		if err != nil {
			if errors.Is(err, bufio.ErrBufferFull) {
				continue
			}
			if errors.Is(err, io.EOF) {
				if len(collected) > 0 || record.Truncated {
					record.Line = string(collected)
					return record, true, nil
				}
				return record, false, io.EOF
			}
			return record, false, err
		}
	}
}

// truncateUTF8 is the shared rune-safe truncation helper. It lives in the adapter
// package so the snapshot and follow output paths cannot drift apart: a raw byte
// slice on either path would leave the caller with half a character.
func truncateUTF8(data []byte, limit int) []byte {
	return adapter.TruncateUTF8(data, limit)
}

// followEnvironment returns base with PYTHONUNBUFFERED set and the provider
// executable's own directory first on PATH.
//
// PYTHONUNBUFFERED is set unconditionally rather than only when absent: an
// inherited empty or "0" value would silently restore buffering and turn a live
// follow into a stream that only appears at exit.
func followEnvironment(executable string, base []string) []string {
	environment := make([]string, 0, len(base)+2)
	for _, entry := range base {
		if strings.HasPrefix(entry, "PYTHONUNBUFFERED=") {
			continue
		}
		environment = append(environment, entry)
	}
	environment = append(environment, "PYTHONUNBUFFERED=1")
	return providerEnvironment(executable, environment)
}
